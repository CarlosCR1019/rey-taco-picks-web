"""Validated, network-free input contract for social video rendering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import json
import re
from types import MappingProxyType
from typing import Any
from uuid import UUID


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PICK_FIELDS = frozenset({"partido", "pick", "cuota", "categoria", "estado"})
_KINDS = frozenset({"results", "teaser"})
_FORBIDDEN_FIELD_NAMES = frozenset(
    {"token", "telegram_id", "file_id", "email", "pick_id", "source_event_id"}
)


def _uuid(value: object) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("reel input batch id is invalid")
    try:
        normalized = str(UUID(value))
    except ValueError:
        raise ValueError("reel input batch id is invalid") from None
    if normalized != value:
        raise ValueError("reel input batch id is invalid")
    return normalized


def _date(value: object) -> str:
    if isinstance(value, date) and not isinstance(value, str):
        return value.isoformat()
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("reel input portfolio date is invalid")
    try:
        normalized = date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError("reel input portfolio date is invalid") from None
    if normalized != value:
        raise ValueError("reel input portfolio date is invalid")
    return normalized


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("reel input template digest is invalid")
    return value


def _text(value: object, *, field: str, maximum: int = 240) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError(f"reel input {field} is invalid")
    result = str(value).strip()
    if not result or len(result) > maximum or any(ord(char) < 32 and char not in "\n\t" for char in result):
        raise ValueError(f"reel input {field} is invalid")
    return result


@dataclass(frozen=True, slots=True)
class ReelInput:
    batch_id: str
    portfolio_date: str
    kind: str
    picks: tuple[Mapping[str, str], ...]
    editorial_text: str
    template_digest: str
    approved_image_refs: tuple[str, ...]

    def to_json(self) -> str:
        payload = {
            "approved_image_refs": list(self.approved_image_refs),
            "batch_id": self.batch_id,
            "editorial_text": self.editorial_text,
            "kind": self.kind,
            "picks": [dict(item) for item in self.picks],
            "portfolio_date": self.portfolio_date,
            "template_digest": self.template_digest,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_reel_input(
    *,
    batch_id: str,
    portfolio_date: str | date,
    picks: Sequence[Mapping[str, Any]],
    template_digest: str,
    kind: str = "results",
    editorial_text: str = "",
    approved_image_refs: Sequence[str] = (),
) -> ReelInput:
    normalized_batch = _uuid(batch_id)
    normalized_date = _date(portfolio_date)
    if kind not in _KINDS:
        raise ValueError("reel input kind is invalid")
    normalized_digest = _digest(template_digest)
    if not isinstance(picks, Sequence) or isinstance(picks, (str, bytes)) or not 1 <= len(picks) <= 6:
        raise ValueError("reel input requires one to six picks")
    normalized_picks: list[Mapping[str, str]] = []
    for raw_pick in picks:
        if not isinstance(raw_pick, Mapping):
            raise ValueError("reel input pick is invalid")
        extra = set(raw_pick) - _PICK_FIELDS
        if extra or any(str(field).casefold() in _FORBIDDEN_FIELD_NAMES for field in raw_pick):
            raise ValueError("reel input contains forbidden field")
        required = {"partido", "pick", "cuota"}
        if not required.issubset(raw_pick):
            raise ValueError("reel input pick is incomplete")
        normalized: dict[str, str] = {}
        for field in sorted(raw_pick):
            normalized[field] = _text(raw_pick[field], field=field)
        normalized_picks.append(MappingProxyType(normalized))
    if not isinstance(editorial_text, str) or len(editorial_text) > 1000:
        raise ValueError("reel input editorial text is invalid")
    if any(ord(char) < 32 and char not in "\n\t" for char in editorial_text):
        raise ValueError("reel input editorial text is invalid")
    refs: list[str] = []
    for ref in approved_image_refs:
        if (
            not isinstance(ref, str)
            or not ref
            or len(ref) > 512
            or "://" in ref
            or any(ord(char) < 32 or ord(char) == 127 for char in ref)
        ):
            raise ValueError("reel input image reference is invalid")
        refs.append(ref)
    return ReelInput(
        normalized_batch,
        normalized_date,
        kind,
        tuple(normalized_picks),
        editorial_text,
        normalized_digest,
        tuple(refs),
    )
