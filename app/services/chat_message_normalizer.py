"""Normalize casual customer chat text for intent matching — no LLM required."""

from __future__ import annotations

import re


_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bu\b", "you"),
    (r"\bur\b", "your"),
    (r"\br\b", "are"),
    (r"\bhav\b", "have"),
    (r"\bgot\b", "have"),
    (r"\bmch\b", "much"),
    (r"\bdelivry\b", "delivery"),
    (r"\bdeliveri\b", "delivery"),
    (r"\bpostge\b", "postage"),
    (r"\btracksut\b", "tracksuit"),
    (r"\btrack\s*suit\b", "tracksuit"),
    (r"\btrouser\b", "trousers"),
    (r"\breturn\b", "return"),
    (r"\bavail\b", "available"),
    (r"\bstock\b", "stock"),
    (r"\bcheaper\b", "cheaper"),
    (r"\bcolour\b", "colour"),
    (r"\bcolor\b", "colour"),
    (r"\blrg\b", "large"),
    (r"\blge\b", "large"),
    (r"\bsml\b", "small"),
    (r"\bmed\b", "medium"),
    (r"\bpls\b", "please"),
    (r"\bthx\b", "thanks"),
    (r"\bwhen will it come\b", "when will delivery arrive"),
    (r"\bhow mch\b", "how much"),
    (r"\bcan i return\b", "can i return"),
    (r"\bshow cheaper\b", "show cheaper"),
    (r"\bgot any\b", "do you have any"),
    (r"\bhav u got\b", "do you have"),
    (r"\bhave u got\b", "do you have"),
)


def normalize_customer_message(message: str) -> str:
    """Lightweight spelling/abbreviation normalization for rule matching."""
    text = (message or "").strip()
    if not text:
        return text
    lower = text.lower()
    for pattern, replacement in _REPLACEMENTS:
        lower = re.sub(pattern, replacement, lower, flags=re.I)
    # Collapse repeated whitespace
    return re.sub(r"\s+", " ", lower).strip()
