"""Fail-closed retrieval and inspection of original Telegram ticket evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import logging
from pathlib import Path
import re
from typing import Callable, Literal, Protocol
import unicodedata
import warnings

from PIL import Image, UnidentifiedImageError
import pytesseract
import requests

from backend.result_reporting import ResultReport
from backend.vertical_repository import TicketCandidate


LOGGER = logging.getLogger(__name__)
_EMPTY_DIGEST = sha256(b"").hexdigest()
_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{1,512}$")
_MAX_METADATA_BYTES = 256 * 1024
_MAX_TICKET_BYTES = 10 * 1024 * 1024
_MAX_OCR_CHARACTERS = 256 * 1024


@dataclass(frozen=True, slots=True)
class EvidenceDecision:
    state: Literal["matched", "pending_review"]
    ticket_id: str
    pick_ids: tuple[int, ...]
    ocr_digest: str


@dataclass(frozen=True, slots=True)
class MatchedEvidence:
    evidence_id: str
    ticket_id: str
    media_digest: str
    pick_ids: tuple[int, ...]
    jpeg: bytes


class _EvidenceRepository(Protocol):
    def candidates(self, *, portfolio_date: str) -> tuple[TicketCandidate, ...]: ...

    def record(
        self,
        *,
        candidate: TicketCandidate,
        report: ResultReport,
        decision: EvidenceDecision,
        media_digest: str,
    ) -> None: ...


class _TicketFetcher(Protocol):
    def fetch(self, file_id: str) -> bytes: ...


class TelegramTicketFetcher:
    """Recover one Telegram photo without accepting alternate download hosts."""

    def __init__(self, token: str, *, session: object | None = None) -> None:
        if (
            not isinstance(token, str)
            or not token
            or token != token.strip()
            or any(character.isspace() for character in token)
        ):
            raise ValueError("Telegram bot token is required")
        self._token = token
        self._session = session or requests.Session()

    def _bounded_json_post(
        self, method: str, payload: dict[str, str]
    ) -> Mapping[str, object]:
        try:
            response = self._session.post(
                f"https://api.telegram.org/bot{self._token}/{method}",
                data=payload,
                timeout=30,
                stream=True,
                allow_redirects=False,
            )
            raw = _bounded_response_bytes(
                response,
                max_bytes=_MAX_METADATA_BYTES,
                error="Telegram file metadata failed",
            )
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            raise RuntimeError("Telegram file metadata failed") from None
        if (
            not isinstance(parsed, Mapping)
            or parsed.get("ok") is not True
            or not isinstance(parsed.get("result"), Mapping)
        ):
            raise RuntimeError("Telegram file metadata failed")
        return parsed["result"]

    def fetch(self, file_id: str) -> bytes:
        if not isinstance(file_id, str) or _FILE_ID.fullmatch(file_id) is None:
            raise ValueError("Telegram file id is invalid")
        metadata = self._bounded_json_post("getFile", {"file_id": file_id})
        file_path = _safe_telegram_path(metadata)
        try:
            response = self._session.get(
                f"https://api.telegram.org/file/bot{self._token}/{file_path}",
                timeout=30,
                stream=True,
                allow_redirects=False,
            )
        except Exception:
            raise RuntimeError("Telegram ticket download failed") from None
        return _bounded_jpeg(response, max_bytes=_MAX_TICKET_BYTES)


class EvidenceInspector:
    PRIVATE = re.compile(
        r"\b(?:saldo|nombre|tel[eé]fono|correo|e-?mail|usuario|clabe|"
        r"direcci[oó]n|domicilio|cuenta|contacto|titular|beneficiario)\b",
        re.I,
    )
    TICKET_ID = re.compile(r"\bID\s*[:#]?\s*([0-9]{6,20})\b", re.I)
    PRIVATE_VALUE = re.compile(
        r"(?:[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|"
        r"(?<!\d)(?:\+?52[\s().-]*)?(?:\d[\s().-]*){10}(?!\d)|"
        r"(?<!\d)\d{16,18}(?!\d))",
        re.I,
    )

    def __init__(self, *, ocr: Callable[[bytes], str]) -> None:
        if not callable(ocr):
            raise ValueError("ticket OCR must be callable")
        self._ocr = ocr

    def inspect(self, jpeg: bytes, *, report: ResultReport) -> EvidenceDecision:
        if not isinstance(report, ResultReport) or report.kind != "final" or not report.terminal:
            raise ValueError("ticket evidence requires a final report")
        try:
            _validate_jpeg_bytes(jpeg, max_bytes=_MAX_TICKET_BYTES)
            raw_text = self._ocr(jpeg)
            if not isinstance(raw_text, str) or len(raw_text) > _MAX_OCR_CHARACTERS:
                raise ValueError
            text = " ".join(raw_text.split())
        except Exception:
            return EvidenceDecision("pending_review", "", (), _EMPTY_DIGEST)
        digest = sha256(text.encode("utf-8")).hexdigest()
        ticket = self.TICKET_ID.search(text)
        privacy_text = self.TICKET_ID.sub("", text)
        if (
            self.PRIVATE.search(text)
            or self.PRIVATE_VALUE.search(privacy_text)
            or ticket is None
        ):
            return EvidenceDecision("pending_review", "", (), digest)
        matched = tuple(
            int(row["id"])
            for row in report.rows
            if _event_and_score_match(text, row)
        )
        if (
            not 1 <= len(matched) <= min(6, len(report.rows))
            or len(set(matched)) != len(matched)
        ):
            return EvidenceDecision("pending_review", ticket.group(1), (), digest)
        return EvidenceDecision("matched", ticket.group(1), matched, digest)


def _event_and_score_match(text: str, row: Mapping[str, object]) -> bool:
    try:
        event = _fold(str(row["partido"]), keep_hyphen=False)
        teams = [
            _word_fold(team)
            for team in re.split(r"\s+(?:vs[.]?|v[.]?)\s+", event)
            if team.strip()
        ]
        score = _score_pattern(row["resultado_marcador"])
    except (KeyError, TypeError, ValueError):
        return False
    haystack = f" {_word_fold(text)} "
    return (
        len(teams) == 2
        and all(team and f" {team} " in haystack for team in teams)
        and score.search(_fold(text, keep_hyphen=True)) is not None
    )


def _fold(value: str, *, keep_hyphen: bool) -> str:
    value = value.replace("–", "-").replace("—", "-")
    folded = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    # Playdoit renders final scores with a colon (for example ``5:0``), while
    # database results are normalized with a hyphen. Preserve both separators
    # for the score matcher; team-name folding removes them afterwards.
    allowed = r"[^a-z0-9\s:-]" if keep_hyphen else r"[^a-z0-9\s.-]"
    return " ".join(re.sub(allowed, " ", folded).split())


def _word_fold(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _fold(value, keep_hyphen=False)).split())


def _score_pattern(value: object) -> re.Pattern[str]:
    if not isinstance(value, str):
        raise ValueError
    normalized = value.replace("–", "-").replace("—", "-")
    match = re.fullmatch(r"\s*([0-9]{1,3})\s*-\s*([0-9]{1,3})\s*", normalized)
    if match is None:
        raise ValueError
    return re.compile(
        rf"(?<![0-9]){re.escape(match.group(1))}\s*[-:]\s*"
        rf"{re.escape(match.group(2))}(?![0-9])"
    )


def _safe_telegram_path(payload: Mapping[str, object]) -> str:
    value = payload.get("file_path")
    if (
        not isinstance(value, str)
        or value != value.strip()
        or re.fullmatch(r"photos/[A-Za-z0-9_.-]{1,180}", value) is None
    ):
        raise RuntimeError("Telegram file path was invalid")
    return value


def _bounded_jpeg(response: object, *, max_bytes: int) -> bytes:
    value = _bounded_response_bytes(
        response,
        max_bytes=max_bytes,
        error="Telegram ticket download failed",
    )
    try:
        _validate_jpeg_bytes(value, max_bytes=max_bytes)
        return value
    except Exception:
        raise RuntimeError("Telegram ticket download failed") from None


def _bounded_response_bytes(
    response: object,
    *,
    max_bytes: int,
    error: str,
) -> bytes:
    try:
        if getattr(response, "status_code", None) != 200:
            raise RuntimeError(error)
        headers = getattr(response, "headers", {})
        raw_length = headers.get("Content-Length") if isinstance(headers, Mapping) else None
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except (TypeError, ValueError):
                raise RuntimeError(error) from None
            if declared_length < 0 or declared_length > max_bytes:
                raise RuntimeError(error)
        iterator = getattr(response, "iter_content", None)
        if not callable(iterator):
            raise RuntimeError(error)
        data = bytearray()
        for chunk in iterator(64 * 1024):
            if not isinstance(chunk, bytes) or len(data) + len(chunk) > max_bytes:
                raise RuntimeError(error)
            data.extend(chunk)
        return bytes(data)
    except Exception:
        raise RuntimeError(error) from None
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _validate_jpeg_bytes(value: object, *, max_bytes: int) -> None:
    if (
        not isinstance(value, bytes)
        or len(value) < 4
        or len(value) > max_bytes
        or not value.startswith(b"\xff\xd8")
        or not value.endswith(b"\xff\xd9")
    ):
        raise ValueError("ticket evidence requires valid JPEG bytes")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(value)) as image:
                if image.format != "JPEG" or image.width <= 0 or image.height <= 0:
                    raise ValueError
                image.load()
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        ValueError,
    ):
        raise ValueError("ticket evidence requires valid JPEG bytes") from None


def tesseract_ocr(jpeg: bytes) -> str:
    _validate_jpeg_bytes(jpeg, max_bytes=_MAX_TICKET_BYTES)
    with Image.open(BytesIO(jpeg)) as image:
        image.load()
        return pytesseract.image_to_string(image.convert("RGB"), lang="spa+eng")


def collect_matched_evidence(
    report: ResultReport,
    *,
    repository: _EvidenceRepository,
    fetcher: _TicketFetcher,
    inspector: EvidenceInspector,
) -> tuple[MatchedEvidence, ...]:
    matched: list[MatchedEvidence] = []
    for candidate in repository.candidates(portfolio_date=report.portfolio_date):
        media_digest = _EMPTY_DIGEST
        try:
            jpeg = fetcher.fetch(candidate.file_id)
            media_digest = sha256(jpeg).hexdigest()
            decision = inspector.inspect(jpeg, report=report)
        except Exception:
            jpeg = b""
            decision = EvidenceDecision(
                "pending_review", "", (), _EMPTY_DIGEST
            )
        try:
            repository.record(
                candidate=candidate,
                report=report,
                decision=decision,
                media_digest=media_digest,
            )
        except Exception:
            LOGGER.warning("ticket evidence status=pending_review")
            continue
        if decision.state == "matched":
            matched.append(
                MatchedEvidence(
                    candidate.evidence_key,
                    decision.ticket_id,
                    media_digest,
                    decision.pick_ids,
                    jpeg,
                )
            )
        elif decision.state == "pending_review":
            LOGGER.warning("ticket evidence status=pending_review")
    return tuple(matched)


def collect_local_matched_evidence(
    report: ResultReport,
    *,
    tickets_dir: Path,
    inspector: EvidenceInspector,
    max_candidates: int = 50,
) -> tuple[MatchedEvidence, ...]:
    """Recover bounded, repository-owned ticket images for legacy evidence."""
    if not isinstance(tickets_dir, Path):
        raise ValueError("local ticket directory is invalid")
    if (
        type(max_candidates) is not int
        or not 1 <= max_candidates <= 100
    ):
        raise ValueError("local ticket candidate limit is invalid")
    manifest = tickets_dir / "manifest.json"
    try:
        raw_manifest = manifest.read_bytes()
        if len(raw_manifest) > _MAX_METADATA_BYTES:
            raise ValueError
        names = json.loads(raw_manifest.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(names, list):
        return ()

    matched: list[MatchedEvidence] = []
    seen_digests: set[str] = set()
    for raw_name in names[:max_candidates]:
        if (
            not isinstance(raw_name, str)
            or re.fullmatch(r"ticket_[0-9]{1,20}[.]jpg", raw_name) is None
        ):
            continue
        try:
            jpeg = (tickets_dir / raw_name).read_bytes()
            _validate_jpeg_bytes(jpeg, max_bytes=_MAX_TICKET_BYTES)
        except (OSError, ValueError):
            continue
        media_digest = sha256(jpeg).hexdigest()
        if media_digest in seen_digests:
            continue
        decision = inspector.inspect(jpeg, report=report)
        if decision.state != "matched":
            continue
        seen_digests.add(media_digest)
        matched.append(
            MatchedEvidence(
                evidence_id=raw_name,
                ticket_id=decision.ticket_id,
                media_digest=media_digest,
                pick_ids=decision.pick_ids,
                jpeg=jpeg,
            )
        )
    return tuple(matched)
