"""Image helpers: thumbnail generation, EXIF read, format detection.

Pillow is imported lazily; if missing the functions return sensible fallbacks
so the rest of the app keeps working.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _pil():
    try:
        from PIL import Image, ImageOps  # type: ignore
        return Image, ImageOps
    except Exception as exc:  # pragma: no cover - Pillow missing
        logger.warning("Pillow not available: %s", exc)
        return None, None


def read_dimensions(path: Path) -> Tuple[Optional[int], Optional[int]]:
    Image, _ = _pil()
    if Image is None:
        return None, None
    try:
        with Image.open(str(path)) as im:
            return im.width, im.height
    except Exception as exc:
        logger.debug("read_dimensions failed for %s: %s", path, exc)
        return None, None


def make_thumbnail(src: Path, dst: Path, size: Tuple[int, int] = (480, 480)) -> Optional[Path]:
    """Write a JPEG thumbnail to ``dst``; return ``dst`` or ``None`` on failure."""
    Image, ImageOps = _pil()
    if Image is None:
        return None
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(str(src)) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail(size, Image.LANCZOS)
            if im.mode in ("RGBA", "P", "LA"):
                im = im.convert("RGB")
            im.save(str(dst), "JPEG", quality=85, optimize=True)
        return dst
    except Exception as exc:
        logger.warning("make_thumbnail failed for %s: %s", src, exc)
        return None


def make_test_image(dst: Path, label: str = "VC") -> Path:
    """Create a deterministic dummy image on disk (used for tests)."""
    Image, _ = _pil()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if Image is None:
        # Minimal JPEG fallback (~1x1 grey pixel) so tests still work without PIL.
        # Tiny pre-encoded grey JPEG (67 bytes).
        raw = bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
            "07090908070a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc2000b08000100010101110000ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc4001f0100030101010101010101010000000000000102030405060708090a0bffda0008010100003f00fbff00d9"
        )
        dst.write_bytes(raw)
        return dst
    from PIL import ImageDraw, ImageFont
    im = Image.new("RGB", (640, 640), color=(30, 30, 30))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 36)
    except Exception:
        font = ImageFont.load_default()
    d.text((40, 280), label, fill=(220, 220, 220), font=font)
    im.save(str(dst), "JPEG", quality=85)
    return dst
