"""AI provider adapters with a unified interface.

Each provider returns a structured dict matching::

    {
        "artist": str | None,
        "title": str | None,
        "label": str | None,
        "catalog_number": str | None,
        "barcode": str | None,
        "year": int | None,
        "format": str | None,
        "country": str | None,
        "genre": str | None,
        "notes": str | None,
        "confidence": "high" | "low" | "unknown",
        "reason": str,
    }

Network calls are isolated and lazy-imported.  When ``httpx`` or a provider's
SDK is not installed we still raise a clean ``RuntimeError`` so the UI can show
a clear message instead of a stack trace.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _b64_image(path: Path) -> str:
    data = path.read_bytes()
    return base64.b64encode(data).decode("ascii")


PROMPT_TEMPLATE = (
    "You are cataloguing a vinyl record from photos. Each photo has a role: "
    "{roles}. Look at the images and return STRICT JSON with these keys: "
    "artist, title, label, catalog_number, barcode, year (integer), format, "
    "country, genre, notes, confidence ('high'/'low'/'unknown'), reason "
    "(short sentence explaining confidence). "
    "If a field is not visible, set it to null. Do not invent values. "
    "Return only valid JSON, no prose."
)

CONFIDENCE_MAP = {"high": "high", "low": "low", "unknown": "unknown"}


def _normalise_ai_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.cleaning import clean_str, clean_int
    return {
        "artist": clean_str(raw.get("artist")),
        "title": clean_str(raw.get("title")),
        "label": clean_str(raw.get("label")),
        "catalog_number": clean_str(raw.get("catalog_number")),
        "barcode": clean_str(raw.get("barcode")),
        "year": clean_int(raw.get("year")),
        "format": clean_str(raw.get("format")),
        "country": clean_str(raw.get("country")),
        "genre": clean_str(raw.get("genre")),
        "notes": clean_str(raw.get("notes")),
        "confidence": CONFIDENCE_MAP.get(str(raw.get("confidence") or "").lower(), "unknown"),
        "reason": clean_str(raw.get("reason")) or "No reason given",
    }


def _extract_json(text: str) -> Dict[str, Any]:
    """Extract the first JSON object from ``text``."""
    if not text:
        return {}
    # Try direct parse first
    try:
        return json.loads(text)
    except Exception:
        pass
    # Greedy object match
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


class AIProvider:
    """Base interface; concrete providers subclass and implement ``call``."""

    name = "base"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def call(self, images: List[Dict[str, Any]]) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


class OpenAIProvider(AIProvider):
    name = "openai"

    def call(self, images: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            import httpx  # type: ignore
        except Exception as exc:
            raise RuntimeError("httpx is required for OpenAI calls") from exc
        if not self.api_key:
            raise RuntimeError("OpenAI API key not configured")
        content: List[Dict[str, Any]] = []
        for img in images:
            content.append({
                "type": "text",
                "text": f"Role: {img.get('role', 'other')}",
            })
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img['b64']}"},
            })
        payload = {
            "model": self.model or "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": content},
                {"role": "user", "content": PROMPT_TEMPLATE.format(
                    roles=", ".join(img.get("role", "other") for img in images)
                )},
            ],
            "temperature": 0.0,
        }
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json=payload, timeout=60.0,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        return _normalise_ai_result(_extract_json(text))


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def call(self, images: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            import httpx  # type: ignore
        except Exception as exc:
            raise RuntimeError("httpx is required for Anthropic calls") from exc
        if not self.api_key:
            raise RuntimeError("Anthropic API key not configured")
        content: List[Dict[str, Any]] = []
        for img in images:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg",
                            "data": img["b64"]},
            })
            content.append({"type": "text", "text": f"Role: {img.get('role','other')}"})
        content.append({"type": "text",
                        "text": PROMPT_TEMPLATE.format(
                            roles=", ".join(img.get("role","other") for img in images))})
        payload = {"model": self.model or "claude-3-5-sonnet-latest",
                   "max_tokens": 1024, "messages": [{"role": "user", "content": content}]}
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json=payload, timeout=60.0,
        )
        r.raise_for_status()
        text = "".join(
            block.get("text", "") for block in r.json().get("content", [])
            if block.get("type") == "text"
        )
        return _normalise_ai_result(_extract_json(text))


class GeminiProvider(AIProvider):
    name = "gemini"

    def call(self, images: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            import httpx  # type: ignore
        except Exception as exc:
            raise RuntimeError("httpx is required for Gemini calls") from exc
        if not self.api_key:
            raise RuntimeError("Gemini API key not configured")
        parts: List[Dict[str, Any]] = []
        for img in images:
            parts.append({"text": f"Role: {img.get('role','other')}"})
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": img["b64"]}})
        parts.append({"text": PROMPT_TEMPLATE.format(
            roles=", ".join(img.get("role","other") for img in images))})
        model = self.model or "gemini-1.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        r = httpx.post(url, params={"key": self.api_key},
                       json={"contents": [{"role": "user", "parts": parts}]},
                       timeout=60.0)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _normalise_ai_result(_extract_json(text))


def get_provider(name: str, api_key: str, model: str) -> AIProvider:
    """Factory that returns the right provider based on ``name``."""
    name = (name or "openai").lower()
    if name == "anthropic":
        return AnthropicProvider(api_key, model)
    if name == "gemini":
        return GeminiProvider(api_key, model)
    return OpenAIProvider(api_key, model)


def call_ai(provider: str, api_key: str, model: str,
            image_paths: List[Path], roles: List[str]) -> Dict[str, Any]:
    """Public helper: encode images, call provider, return normalised dict."""
    images = [{"role": roles[i] if i < len(roles) else "other",
               "b64": _b64_image(p)}
              for i, p in enumerate(image_paths)]
    return get_provider(provider, api_key, model).call(images)
