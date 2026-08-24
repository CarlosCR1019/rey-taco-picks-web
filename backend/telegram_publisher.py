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
        messages = chunk_messages(
            payload,
            destination=destination.name,
            total_count=len(full_batch),
        )
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


def chunk_messages(
    picks: Iterable[Mapping[str, object]],
    *,
    destination: Literal["admin", "vip", "free"] = "admin",
    total_count: int | None = None,
) -> list[str]:
    """Build destination-aware messages without splitting a selection block."""
    if destination not in _SUPPORTED_DESTINATIONS:
        raise ValueError("Telegram destination must be admin, vip, or free")
    rows = list(picks)
    if not rows:
        return []

    if destination == "admin":
        return _chunk_blocks([format_pick_block(row) for row in rows])

    portfolio_total = total_count if isinstance(total_count, int) and total_count >= len(rows) else len(rows)
    blocks = [
        _editorial_pick_block(row, index=index, include_rationale=destination == "vip")
        for index, row in enumerate(rows, start=1)
    ]
    if destination == "vip":
        header = (
            "👑 REY TACO PICKS • CARTERA VIP\n"
            f"📋 {portfolio_total} selecciones preparadas para la jornada"
        )
        footer = (
            "🔒 Cartera completa incluida en tu acceso VIP.\n"
            "Los momios pueden cambiar. 18+ · Juega con responsabilidad."
        )
    else:
        public_count = len(rows)
        additional = max(0, portfolio_total - public_count)
        header = (
            "🌮 REY TACO PICKS • PICKS PÚBLICOS\n"
            f"Hoy compartimos {public_count} de las {portfolio_total} selecciones de la jornada."
        )
        footer_lines = []
        if additional:
            footer_lines.append(
                f"👑 La cartera VIP incluye {additional} selecciones adicionales antes de los partidos."
            )
        footer_lines.extend(
            (
                "👉 Consulta el acceso VIP en reytacopicks.com",
                "Los momios pueden cambiar. 18+ · Juega con responsabilidad.",
            )
        )
        footer = "\n".join(footer_lines)
    return _chunk_blocks(blocks, header=header, footer=footer)


def format_pick_block(pick: Mapping[str, object]) -> str:
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
    notice = "Nota: análisis informativo; no garantiza resultados."

    rationale = _field(pick, ("razonamiento", "razon", "rationale", "analysis"), "No especificada", MAX_MESSAGE_LENGTH)
    prefix = "\n".join(lines) + "\nRationale: "
    available = MAX_MESSAGE_LENGTH - len(prefix) - 1 - len(notice)
    bounded_rationale = _truncate(rationale, max(0, available))
    return f"{prefix}{bounded_rationale}\n{notice}"


def _editorial_pick_block(
    pick: Mapping[str, object],
    *,
    index: int,
    include_rationale: bool,
) -> str:
    event = _field(pick, ("partido", "event", "evento"), "Evento por confirmar", 600)
    schedule = _field(pick, ("horario", "schedule"), "Horario por confirmar", 240)
    selection = _field(pick, ("pick",), "Selección por confirmar", 600)
    price = _field(pick, ("cuota", "price", "odds"), "Por confirmar", 120)
    confidence = _field(pick, ("confianza", "confidence"), "No disponible", 120)
    lines = [
        f"🎯 {index}. {event}",
        f"🕒 {schedule}",
        f"✅ Selección: {selection}",
        f"💰 Momio observado: {price}",
        f"📊 {format_evidence_support(confidence)}",
    ]
    if include_rationale:
        rationale = _field(pick, ("razonamiento", "razon", "rationale", "analysis"), "", 1_200)
        if _meaningful_rationale(rationale):
            lines.append(f"🧠 Lectura del Rey: {rationale}")
    return "\n".join(lines)


def _meaningful_rationale(value: str) -> bool:
    normalized = " ".join(value.casefold().split()).rstrip(".")
    return bool(normalized) and normalized not in {
        "no especificada",
        "no especificado",
        "not specified",
        "n/a",
    }


def _chunk_blocks(blocks: list[str], *, header: str = "", footer: str = "") -> list[str]:
    """Pack complete blocks under Telegram's limit, repeating context per chunk."""
    messages: list[str] = []
    current: list[str] = []
    for block in blocks:
        candidate = _compose_message(header, [*current, block], footer)
        if len(candidate) <= MAX_MESSAGE_LENGTH:
            current.append(block)
            continue
        if current:
            messages.append(_compose_message(header, current, footer))
            current = []
        single = _compose_message(header, [block], footer)
        if len(single) > MAX_MESSAGE_LENGTH:
            overhead = len(_compose_message(header, [""], footer))
            block = _truncate(block, max(0, MAX_MESSAGE_LENGTH - overhead))
        current.append(block)
    if current:
        messages.append(_compose_message(header, current, footer))
    return messages


def _compose_message(header: str, blocks: list[str], footer: str) -> str:
    sections = [section for section in (header, "\n\n".join(blocks), footer) if section]
    return "\n\n".join(sections)


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
