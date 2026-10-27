"""Discogs HTTP client with rate limiting (60 req/min) and retries."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .scoring import parse_release, parse_search_results, suggest_price_eur

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.discogs.com/database/search"
RELEASE_URL = "https://api.discogs.com/releases/{rid}"

# 60 req/min = 1 req per second minimum; we use 1.05s to be safe.
MIN_INTERVAL_S = 1.05


class RateLimiter:
    """Simple token-bucket-ish limiter: 60 calls per 60 seconds."""

    def __init__(self, per_minute: int = 60):
        self.per_minute = per_minute
        self.window: List[float] = []
        self._lock_until = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        # Honour explicit lockout first
        if now < self._lock_until:
            time.sleep(self._lock_until - now)
            now = time.monotonic()
        # Drop entries outside the 60s window
        self.window = [t for t in self.window if now - t < 60.0]
        if len(self.window) >= self.per_minute:
            sleep_for = 60.0 - (now - self.window[0]) + 0.05
            sleep_for = max(sleep_for, MIN_INTERVAL_S)
            logger.debug("Rate limiter sleeping %.2fs", sleep_for)
            time.sleep(sleep_for)
            now = time.monotonic()
            self.window = [t for t in self.window if now - t < 60.0]
        # Always enforce minimum spacing between consecutive calls
        if self.window:
            gap = now - self.window[-1]
            if gap < MIN_INTERVAL_S:
                time.sleep(MIN_INTERVAL_S - gap)
                now = time.monotonic()
        self.window.append(now)

    def force_lockout(self, seconds: float) -> None:
        self._lock_until = max(self._lock_until, time.monotonic() + seconds)


_LIM = RateLimiter()


def _cache_key(prefix: str, payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return f"{prefix}:v1:{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


class DiscogsClient:
    """Thin wrapper around the public Discogs API."""

    def __init__(self, token: str, user_agent: str,
                 cache_repo: Optional[Any] = None):
        self.token = token
        self.user_agent = user_agent
        self.cache_repo = cache_repo  # app.db.repository.Repo | None

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Discogs token={self.token}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

    def _http(self) -> Any:
        try:
            import httpx  # type: ignore
        except Exception as exc:
            raise RuntimeError("httpx is required for Discogs calls") from exc
        return httpx

    def search(self, query: str, per_page: int = 10) -> Dict[str, Any]:
        """Search the Discogs database. Returns ``{results: [...]}``."""
        if not self.token:
            raise RuntimeError("Discogs token not configured")
        params = {"q": query, "type": "release", "per_page": int(per_page)}
        key = _cache_key("search", params)
        if self.cache_repo:
            cached = self.cache_repo.cache_get("discogs_cache", key)
            if cached:
                try:
                    return json.loads(cached["payload"])
                except Exception:
                    pass
        _LIM.wait()
        httpx = self._http()
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                r = httpx.get(SEARCH_URL, params=params,
                              headers=self._headers(), timeout=30.0)
                if r.status_code == 429:
                    retry_after = float(r.headers.get("Retry-After", "60"))
                    _LIM.force_lockout(retry_after)
                    _LIM.wait()
                    continue
                r.raise_for_status()
                data = r.json()
                if self.cache_repo:
                    self.cache_repo.cache_set(
                        "discogs_cache", key, data, query=query
                    )
                return data
            except Exception as exc:
                last_exc = exc
                logger.warning("Discogs search attempt %s failed: %s", attempt + 1, exc)
                _LIM.wait()
        raise RuntimeError(f"Discogs search failed: {last_exc}")

    def release(self, release_id: int) -> Dict[str, Any]:
        """Fetch one release by id."""
        if not self.token:
            raise RuntimeError("Discogs token not configured")
        key = _cache_key("release", {"id": int(release_id)})
        if self.cache_repo:
            cached = self.cache_repo.cache_get("discogs_cache", key)
            if cached:
                try:
                    return json.loads(cached["payload"])
                except Exception:
                    pass
        _LIM.wait()
        httpx = self._http()
        url = RELEASE_URL.format(rid=release_id)
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                r = httpx.get(url, headers=self._headers(), timeout=30.0)
                if r.status_code == 429:
                    retry_after = float(r.headers.get("Retry-After", "60"))
                    _LIM.force_lockout(retry_after)
                    _LIM.wait()
                    continue
                r.raise_for_status()
                data = r.json()
                if self.cache_repo:
                    self.cache_repo.cache_set(
                        "discogs_cache", key, data, query=f"id:{release_id}"
                    )
                return data
            except Exception as exc:
                last_exc = exc
                logger.warning("Discogs release attempt %s failed: %s", attempt + 1, exc)
                _LIM.wait()
        raise RuntimeError(f"Discogs release fetch failed: {last_exc}")

    def search_for_record(
        self, artist: Optional[str], title: Optional[str],
        catalog_number: Optional[str] = None,
        barcode: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Build a smart query from the AI-extracted fields."""
        parts: List[str] = []
        for v in (artist, title):
            if v:
                parts.append(v)
        if catalog_number and not title:
            parts.append(catalog_number)
        if barcode:
            parts.append(barcode)
        query = " ".join(parts).strip()
        if not query:
            return []
        payload = self.search(query, per_page=10)
        return parse_search_results(payload)

    def enrich(self, ai_data: Dict[str, Any]) -> Dict[str, Any]:
        """Run search + ranking + price suggestion for one record.

        Returns ``{selected, candidates, confidence, reason, prices}``.
        """
        from .scoring import auto_select, rank_candidates
        candidates = self.search_for_record(
            ai_data.get("artist"), ai_data.get("title"),
            ai_data.get("catalog_number"), ai_data.get("barcode"),
        )
        if not candidates:
            return {
                "selected": None, "candidates": [],
                "confidence": "unknown",
                "reason": "No candidates found",
                "prices": None,
            }
        ranked = rank_candidates(ai_data, candidates)
        selected, confidence, score = auto_select(ai_data, candidates)
        prices: Optional[Dict[str, Any]] = None
        if selected and selected.get("id"):
            try:
                full = parse_release(self.release(int(selected["id"])))
                selected = {**selected, **full}
                ps = suggest_price_eur(full.get("price_suggestions") or [])
                prices = ps.to_dict()
            except Exception as exc:
                logger.warning("Could not fetch full release: %s", exc)
        return {
            "selected": selected,
            "candidates": ranked,
            "confidence": confidence,
            "reason": f"top score={score:.1f}",
            "prices": prices,
            "top_score": score,
        }
