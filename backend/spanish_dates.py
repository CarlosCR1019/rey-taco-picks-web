"""Small locale-independent Spanish date labels for social artifacts."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


_SPANISH_MONTHS = (
    "ENERO",
    "FEBRERO",
    "MARZO",
    "ABRIL",
    "MAYO",
    "JUNIO",
    "JULIO",
    "AGOSTO",
    "SEPTIEMBRE",
    "OCTUBRE",
    "NOVIEMBRE",
    "DICIEMBRE",
)


def cdmx_banner_date(value: date | datetime | None = None) -> str:
    """Return an uppercase Spanish calendar label in Mexico City time."""

    current = value
    if current is None:
        current = datetime.now(ZoneInfo("America/Mexico_City"))
    elif isinstance(current, datetime) and current.tzinfo is not None:
        current = current.astimezone(ZoneInfo("America/Mexico_City"))
    if not isinstance(current, (date, datetime)):
        raise TypeError("banner date must be a date or datetime")
    return (
        f"{current.day:02d} DE {_SPANISH_MONTHS[current.month - 1]}, "
        f"{current.year} • CDMX"
    )
