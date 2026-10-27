"""Image grouping and storage helpers.

Given a flat folder of image files (mixed orientation, mixed sources), we
group consecutive filenames (sorted by name + EXIF datetime when present) into
sets of N images per record. The trailing set is flagged if it has fewer than
``expected_per_record`` images.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic"}

# Filename patterns we try to detect per-position role
_ROLE_PATTERNS = [
    (re.compile(r"(front|cover|frontcover)", re.I), "front"),
    (re.compile(r"(back|rear)", re.I), "back"),
    (re.compile(r"(label.?a|side.?a|sidea)", re.I), "label_a"),
    (re.compile(r"(label.?b|side.?b|sideb)", re.I), "label_b"),
    (re.compile(r"(inner|sleeve|innersleeve)", re.I), "inner_sleeve"),
]
_DEFAULT_ROLE_ORDER = ["front", "back", "label_a", "label_b", "inner_sleeve", "other"]


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def _file_sort_key(path: Path) -> Tuple[str, float]:
    """Sort by filename (case-insensitive). EXIF time isn't always available;
    we keep the key simple so grouping is deterministic and fast."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (path.name.lower(), mtime)


def list_images(folder: Path) -> List[Path]:
    """Return all image files in ``folder`` (non-recursive) sorted deterministically."""
    if not folder.exists() or not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and is_image_file(p)]
    files.sort(key=_file_sort_key)
    return files


def _infer_role(name: str, position: int, default_order: Sequence[str]) -> str:
    """Guess the role from the filename, falling back to position-based default."""
    for rx, role in _ROLE_PATTERNS:
        if rx.search(name):
            return role
    if 0 <= position < len(default_order):
        return default_order[position]
    return "other"


@dataclass
class ImageGroup:
    """A group of images that together form one record (one record = N images)."""

    files: List[Path]
    roles: List[str]

    @property
    def expected_count(self) -> int:
        return 6  # maximum images per record; trailing group may be shorter

    def is_complete(self) -> bool:
        return len(self.files) == self.expected_count


def group_images(
    files: Sequence[Path],
    images_per_record: int,
    default_order: Optional[Sequence[str]] = None,
) -> List[ImageGroup]:
    """Group a flat image list into fixed-size sets.

    Trailing group is included even if shorter; caller is expected to warn.
    Empty inputs return ``[]``.
    """
    if not files:
        return []
    default_order = list(default_order or _DEFAULT_ROLE_ORDER)
    groups: List[ImageGroup] = []
    for start in range(0, len(files), images_per_record):
        chunk = list(files[start : start + images_per_record])
        roles = [_infer_role(p.name, idx, default_order) for idx, p in enumerate(chunk)]
        groups.append(ImageGroup(files=chunk, roles=roles))
    return groups


def grouping_warning(groups: List[ImageGroup], expected: int) -> Optional[str]:
    """Return a human warning string if the trailing group is incomplete, else None."""
    if not groups:
        return None
    last = groups[-1]
    if len(last.files) < expected:
        return (
            f"Trailing group has only {len(last.files)} of {expected} images "
            f"— it will be imported anyway but you may want to verify."
        )
    return None


def sha1_of_file(path: Path, chunk: int = 65536) -> str:
    """SHA-1 of a file's contents (for de-duplication)."""
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(name: str) -> str:
    """Make ``name`` filesystem-safe (drops path separators and NUL)."""
    name = (name or "").strip()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return safe[:120] or "file"
