"""Application configuration.

Reads/writes ``settings.json`` in a per-user data directory (via ``platformdirs``
with sensible fallbacks so the app also runs without the dependency).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

APP_NAME = "VinylCatalog"
APP_AUTHOR = "VinylCatalog"
SCHEMA_VERSION = 3
DEFAULT_PORT = 8501
DEFAULT_HOST = "0.0.0.0"


def _user_data_dir() -> Path:
    """Return the per-user data directory, creating it if necessary."""
    try:
        import platformdirs  # type: ignore

        d = Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR, roaming=False))
    except Exception:  # fallback without external dep
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_data_dir() -> Path:
    """Public accessor for the user data dir."""
    return _user_data_dir()


@dataclass
class Settings:
    """Runtime configuration persisted to ``settings.json``."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    # AI provider configuration
    ai_provider: str = "openai"  # openai | anthropic | gemini
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    # Discogs configuration
    discogs_token: str = ""
    discogs_user_agent: str = "VinylCatalog/3.0"
    # Misc
    log_level: str = "INFO"
    theme: str = "dark"
    last_image_count: int = 2
    default_roles: list = field(default_factory=lambda: [
        "front", "back", "label_a", "label_b", "inner_sleeve", "other"
    ])
    extras: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Settings":
        p = path or (_user_data_dir() / "settings.json")
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception as exc:
            logger.warning("Failed to load settings from %s: %s", p, exc)
            return cls()

    def save(self, path: Optional[Path] = None) -> Path:
        p = path or (_user_data_dir() / "settings.json")
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        return p
