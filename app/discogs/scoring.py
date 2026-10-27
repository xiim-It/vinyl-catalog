"""Discogs scoring, search and price logic.

Scoring combines artist/title similarity (via ``difflib.SequenceMatcher``) with
catalog-number / barcode exact match bonuses and an LP format bonus. The
top-scoring candidate is auto-selected when its score is >= ``AUTO_THRESHOLD``
(default 60). Otherwise the record is left in ``unknown`` confidence so the
user can pick manually.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import statistics
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.services.cleaning import clean_str

logger = logging.getLogger(__name__)

AUTO_THRESHOLD = 60.0
LP_FORMAT_BONUS = 8.0
CATNO_BONUS = 25.0
BARCODE_BONUS = 25.0
ARTIST_WEIGHT = 0.55
TITLE_WEIGHT = 0.45


def _norm(s: Optional[str]) -> str:
    s = clean_str(s) or ""
    s = s.lower()
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def similarity(a: Optional[str], b: Optional[str]) -> float:
    """Return a 0..100 similarity score between two strings."""
    a = _norm(a)
    b = _norm(b)
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio() * 100.0, 2)


def score_candidate(ai: Dict[str, Any], cand: Dict[str, Any]) -> Tuple[float, str]:
    """Return ``(score, reason)`` for one candidate vs AI-extracted data."""
    artist = similarity(ai.get("artist"), cand.get("artist"))
    title = similarity(ai.get("title"), cand.get("title"))
    score = ARTIST_WEIGHT * artist + TITLE_WEIGHT * title

    cand_catno = _norm(cand.get("catalog_number") or cand.get("catno"))
    ai_catno = _norm(ai.get("catalog_number"))
    if ai_catno and cand_catno and (ai_catno in cand_catno or cand_catno in ai_catno):
        score += CATNO_BONUS

    ai_bc = _norm(ai.get("barcode"))
    cand_bc = _norm(cand.get("barcode"))
    if ai_bc and cand_bc and ai_bc == cand_bc:
        score += BARCODE_BONUS

    fmt = (cand.get("format") or "").upper()
    if "LP" in fmt or "12\"" in fmt or "VINYL" in fmt:
        score += LP_FORMAT_BONUS

    score = min(round(score, 2), 100.0)
    reason = (
        f"artist={artist:.0f} title={title:.0f}"
        + (" +catno" if ai_catno and cand_catno and ai_catno in cand_catno else "")
        + (" +barcode" if ai_bc and cand_bc and ai_bc == cand_bc else "")
        + (" +lp" if "LP" in fmt else "")
    )
    return score, reason


def rank_candidates(
    ai: Dict[str, Any], candidates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Annotate each candidate with ``score`` and ``reason``; return sorted list."""
    annotated: List[Dict[str, Any]] = []
    for c in candidates:
        s, r = score_candidate(ai, c)
        annotated.append({**c, "score": s, "score_reason": r})
    annotated.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return annotated


def auto_select(
    ai: Dict[str, Any], candidates: List[Dict[str, Any]], threshold: float = AUTO_THRESHOLD
) -> Tuple[Optional[Dict[str, Any]], str, float]:
    """Return ``(selected, confidence, top_score)``."""
    if not candidates:
        return None, "unknown", 0.0
    ranked = rank_candidates(ai, candidates)
    top = ranked[0]
    score = top.get("score", 0.0)
    if score >= threshold:
        return top, "high", score
    # Low confidence if any reasonable match exists
    if score >= threshold * 0.5:
        return None, "low", score
    return None, "unknown", score


@dataclass
class PriceSuggestion:
    low_eur: Optional[float]
    high_eur: Optional[float]
    median_eur: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {"low": self.low_eur, "high": self.high_eur, "median": self.median_eur}


def suggest_price_eur(price_suggestions: List[Dict[str, Any]]) -> PriceSuggestion:
    """Pick a low/high price from Discogs ``price_suggestions``.

    Looks at EUR entries (or converts from USD if missing). Returns ``None``
    (not zero) when no usable data is present.
    """
    from app.services.cleaning import clean_float, clean_price_eur
    values_low: List[float] = []
    values_high: List[float] = []
    for ps in price_suggestions or []:
        currency = (ps.get("currency") or "EUR").upper()
        value = ps.get("value")
        if value is None:
            continue
        v = clean_price_eur(value)
        if v is None:
            continue
        if currency == "EUR":
            values_low.append(v)
        elif currency == "USD":
            # Conservative static conversion; user can edit later.
            values_low.append(round(v * 0.92, 2))
    if not values_low and not values_high:
        return PriceSuggestion(None, None, None)
    if values_low:
        values_low.sort()
        n = len(values_low)
        low = round(min(values_low), 2)
        high = round(max(values_low) * 1.5, 2)
        # Median is the statistical median of the observed price values.
        median = round(statistics.median(values_low), 2)
        return PriceSuggestion(low_eur=low, high_eur=high, median_eur=median)
    return PriceSuggestion(None, None, None)


def _norm_release(release: Dict[str, Any]) -> Dict[str, Any]:
    """Map a Discogs ``release`` payload to our internal shape."""
    artists = release.get("artists") or []
    artist = ", ".join(a.get("name", "") for a in artists) if artists else release.get("artist")
    labels = release.get("labels") or []
    label = labels[0].get("name") if labels else release.get("label")
    catno = labels[0].get("catno") if labels else release.get("catno")
    formats = release.get("formats") or []
    fmt = ", ".join(f.get("name", "") for f in formats)
    return {
        "id": release.get("id"),
        "title": release.get("title"),
        "artist": artist,
        "label": label,
        "catalog_number": catno,
        "format": fmt,
        "year": release.get("year"),
        "country": release.get("country"),
        "genre": ", ".join(release.get("genres") or []),
        "style": ", ".join(release.get("styles") or []),
        "thumb": release.get("thumb") or release.get("cover_image"),
        "uri": release.get("uri"),
        "barcode": release.get("barcode") or (release.get("identifiers") or [{}])[0].get("value"),
    }


def parse_search_results(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [_norm_release(r) for r in (payload or {}).get("results", [])]


def parse_release(payload: Dict[str, Any]) -> Dict[str, Any]:
    base = _norm_release(payload)
    base["price_suggestions"] = payload.get("price_suggestions") or []
    base["uri"] = payload.get("uri") or base.get("uri")
    return base
