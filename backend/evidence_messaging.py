"""Normalize evidence-score copy at Python presentation boundaries."""

from __future__ import annotations

import re


_PREFIX = re.compile(r"^respaldo\s+de\s+datos\s*:\s*", re.IGNORECASE)
_SUFFIX = re.compile(r"\s+respaldo\s+de\s+datos\s*$", re.IGNORECASE)


def format_evidence_support(value: object) -> str:
    """Return exactly one neutral label for legacy or productive payloads."""

    text = str(value).strip() if value not in (None, "") else "No disponible"
    text = _PREFIX.sub("", text)
    text = _SUFFIX.sub("", text).strip() or "No disponible"
    return f"Respaldo de datos: {text}"
