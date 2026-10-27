"""Value cleaning helpers used throughout the app.

Treats a fixed set of "placeholder" strings as missing and provides utilities to
coerce values to typed forms (str / int / float / None).
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable, Optional

MISSING_STRINGS = {
    "", "null", "none", "nan", "n/a", "na", "-", "?", "—", "–",
    "unknown", "no data", "n.a.", "n.a", "none.", "nil",
}


def clean_str(value: Any) -> Optional[str]:
    """Return a cleaned string or ``None`` if the value looks missing."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value).strip()
    if s.lower() in MISSING_STRINGS:
        return None
    return s


def clean_int(value: Any) -> Optional[int]:
    """Parse an integer from loose input. Returns ``None`` if missing/invalid."""
    s = clean_str(value)
    if s is None:
        return None
    m = re.search(r"-?\d+", s.replace(",", ""))
    if not m:
        return None
    try:
        return int(m.group(0))
    except (ValueError, TypeError):
        return None


def clean_float(value: Any) -> Optional[float]:
    """Parse a float from loose input. Returns ``None`` if missing/invalid.

    Numeric values are also coerced (so ``0.0`` is preserved unless genuinely
    missing). Strings are only accepted if they parse cleanly.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    s = clean_str(value)
    if s is None:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def clean_price_eur(value: Any) -> Optional[float]:
    """Parse a price in EUR; returns ``None`` for missing values (never 0)."""
    if value is None:
        return None
    if isinstance(value, str):
        # Strip currency symbols and text
        s = re.sub(r"[^\d,.\-]", "", value)
    else:
        s = value
    return clean_float(s)


def merge_keep_existing(existing: Any, new: Any) -> Any:
    """Return ``new`` only if it has a real value, otherwise keep ``existing``.

    "Real value" means not None, not a placeholder string, and (for numbers) a
    finite value. Booleans are treated as missing (only used for confidence
    flags elsewhere).
    """
    if isinstance(new, bool):
        return existing
    if new is None:
        return existing
    if isinstance(new, float) and math.isnan(new):
        return existing
    if isinstance(new, (int, float)):
        return new
    if isinstance(new, str):
        return new if clean_str(new) is not None else existing
    return new if new else existing


def first_present(values: Iterable[Any]) -> Optional[str]:
    """Return the first cleaned string from ``values`` or ``None``."""
    for v in values:
        c = clean_str(v)
        if c is not None:
            return c
    return None
