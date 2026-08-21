"""Small, synchronous Telegram delivery boundary for completed pick batches."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Callable, Iterable, Literal, Mapping, Protocol
import urllib.request

from backend.evidence_messaging import format_evidence_support
from backend.publishing_policy import public_payload


MAX_MESSAGE_LENGTH = 4_000
_SUPPORTED_DESTINATIONS = frozenset({"admin", "vip", "free"})
_DELIVERY_ERROR = "delivery_failed"


@dataclass(frozen=True)
class TelegramDestination:
    name: str
    chat_id: str
    audience: Literal["all", "public"]

    def __post_init__(self) -> None:
        if self.name not in _SUPPORTED_DESTINATIONS:
            raise ValueError("Telegram destination name must be admin, vip, or free")
        if not isinstance(self.chat_id, str) or not self.chat_id.strip():
            raise ValueError("Telegram chat_id must not be empty")
        if self.audience not in ("all", "public"):
            raise ValueError("Telegram audience must be all or public")


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    skipped: bool = False
    error: str = ""
    message_count: int = 0


class TelegramTransport(Protocol):
    def __call__(self, destination: TelegramDestination, text: str) -> None: ...


class _TelegramResponse(Protocol):
    def __enter__(self) -> "_TelegramResponse": ...

    def __exit__(self, *unused: object) -> bool | None: ...

    def getcode(self) -> int: ...

    def read(self) -> bytes: ...


class TelegramHttpTransport:
    """A bounded, token-safe HTTP transport injected into batch delivery."""

    def __init__(
        self,
        token: str,
        timeout: float = 10,
        retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
        urlopen: Callable[..., _TelegramResponse] = urllib.request.urlopen,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Telegram token must not be empty")
        if timeout <= 0:
            raise ValueError("Telegram timeout must be positive")
        if not isinstance(retries, int) or retries < 0:
            raise ValueError("Telegram retries must be a non-negative integer")
        self._token = token
        self._timeout = timeout
        self._retries = retries
        self._sleep = sleep
        self._urlopen = urlopen

    def __call__(self, destination: TelegramDestination, text: str) -> None:
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            data=json.dumps(
                {
                    "chat_id": destination.chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                self._send_once(request)
                return
            except Exception as error:
                last_error = error
                if attempt < self._retries:
                    self._sleep(2**attempt)
        assert last_error is not None
        raise RuntimeError(f"Telegram request failed ({type(last_error).__name__})") from None

    def _send_once(self, request: urllib.request.Request) -> None:
        with self._urlopen(request, timeout=self._timeout) as response:
            if response.getcode() != 200:
                raise RuntimeError("unexpected Telegram HTTP status")
            body = response.read() if callable(getattr(response, "read", None)) else b""
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("invalid Telegram response") from error
        if not isinstance(payload, Mapping) or payload.get("ok") is not True:
            raise RuntimeError("Telegram response was not ok")


def deliver_batch(
    picks: Iterable[Mapping[str, object]],
    destinations: Iterable[TelegramDestination],
    transport: TelegramTransport,
    *,
    completed: frozenset[str] = frozenset(),
) -> dict[str, DeliveryResult]:
    """Send each destination independently; completed and empty rows are harmless skips."""
    full_batch = list(picks)
    results: dict[str, DeliveryResult] = {}
    for destination in destinations:
        if destination.name in completed:
            results[destination.name] = DeliveryResult(success=True, skipped=True)
            continue

        payload = public_payload(full_batch) if destination.audience == "public" else full_batch
        messages = chunk_messages(payload, public=destination.audience == "public")
        if not messages:
            results[destination.name] = DeliveryResult(success=True, skipped=True)
            continue

        sent_count = 0
        try:
            for message in messages:
                transport(destination, message)
                sent_count += 1
        except Exception:
            results[destination.name] = DeliveryResult(
                success=False,
                error=_DELIVERY_ERROR,
                message_count=sent_count,
            )
        else:
            results[destination.name] = DeliveryResult(success=True, message_count=sent_count)
    return results


def chunk_messages(picks: Iterable[Mapping[str, object]], *, public: bool = False) -> list[str]:
    """Fit complete, self-contained pick blocks into Telegram's message limit."""
    messages: list[str] = []
    current = ""
    for row in picks:
        block = format_pick_block(row, public=public)
        if not current:
            current = block
        elif len(current) + 2 + len(block) <= MAX_MESSAGE_LENGTH:
            current = f"{current}\n\n{block}"
        else:
            messages.append(current)
            current = block
    if current:
        messages.append(current)
    return messages


def format_pick_block(pick: Mapping[str, object], *, public: bool = False) -> str:
    """Build a bounded block, preserving the event and pick when rationale is long."""
    event = _field(pick, ("partido", "event", "evento"), "Evento no especificado", 800)
    schedule = _field(pick, ("horario", "schedule"), "", 300)
    selection = _field(pick, ("pick",), "Pick no especificado", 800)
    price = _field(pick, ("cuota", "price", "odds"), "No especificado", 300)
    confidence = _field(pick, ("confianza", "confidence"), "No especificada", 300)
    support = format_evidence_support(confidence)

    lines = [f"Evento: {event}"]
    if schedule:
        lines.append(f"Horario: {schedule}")
    lines.extend(
        [
            f"Pick: {selection}",
            f"Precio: {price}",
            support,
        ]
    )
    notice = (
        "Nota pública: análisis informativo; no garantiza resultados."
        if public
        else "Nota: análisis informativo; no garantiza resultados."
    )
    if public:
        return "\n".join([*lines, notice])

    rationale = _field(pick, ("razonamiento", "razon", "rationale", "analysis"), "No especificada", MAX_MESSAGE_LENGTH)
    prefix = "\n".join(lines) + "\nRationale: "
    available = MAX_MESSAGE_LENGTH - len(prefix) - 1 - len(notice)
    bounded_rationale = _truncate(rationale, max(0, available))
    return f"{prefix}{bounded_rationale}\n{notice}"


def _field(pick: Mapping[str, object], names: tuple[str, ...], default: str, limit: int) -> str:
    for name in names:
        value = pick.get(name)
        if value not in (None, ""):
            return _truncate(str(value).strip(), limit)
    return default


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 0:
        return ""
    if limit == 1:
        return "…"
    return value[: limit - 1] + "…"
