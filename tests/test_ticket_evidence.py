from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
import logging

from PIL import Image
import pytest

from backend.result_reporting import ResultReport
from backend import ticket_listener
from backend.ticket_evidence import (
    EvidenceDecision,
    EvidenceInspector,
    TelegramTicketFetcher,
    collect_matched_evidence,
    collect_local_matched_evidence,
    tesseract_ocr,
)
from backend.vertical_repository import TicketCandidate


BATCH_ID = "44444444-4444-4444-8444-444444444444"
ADMIN_ID = 123456


def final_report() -> ResultReport:
    rows = (
        {
            "id": 101,
            "partido": "Aryans Sports vs Nbp Rainbow AC",
            "resultado_marcador": "5-0",
            "estado": "ganado",
        },
        {
            "id": 102,
            "partido": "Kalighat MS vs East Bengal II",
            "resultado_marcador": "0-2",
            "estado": "ganado",
        },
    )
    return ResultReport(
        batch_id=BATCH_ID,
        portfolio_date="2026-08-24",
        kind="final",
        rows=rows,
        eligible=True,
        terminal=True,
        record="2-0",
        digest="a" * 64,
        telegram="report",
        facebook="report",
        instagram="report",
    )


def jpeg_bytes(*, size: tuple[int, int] = (640, 960)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "white").save(output, format="JPEG")
    return output.getvalue()


class InsertCall:
    def __init__(self, owner: "FakeListenerSupabase", payload: dict[str, object]):
        self.owner = owner
        self.payload = payload

    def execute(self):
        self.owner.order.append("insert")
        return type("Response", (), {"data": [self.payload]})()


class ListenerTable:
    def __init__(self, owner: "FakeListenerSupabase", name: str):
        self.owner = owner
        self.name = name

    def insert(self, payload: dict[str, object]) -> InsertCall:
        self.owner.table_name = self.name
        self.owner.inserted = payload
        return InsertCall(self.owner, payload)


class FakeListenerSupabase:
    def __init__(self, order: list[str]):
        self.order = order
        self.table_name = ""
        self.inserted: dict[str, object] = {}

    def table(self, name: str) -> ListenerTable:
        return ListenerTable(self, name)


def test_listener_persists_admin_origin_and_unique_file_id_without_reordering(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    order: list[str] = []
    fake_supabase = FakeListenerSupabase(order)
    monkeypatch.setattr(ticket_listener, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(ticket_listener, "supabase", fake_supabase)
    monkeypatch.setattr(ticket_listener, "ADMIN_CHAT_ID", ADMIN_ID)
    monkeypatch.setattr(ticket_listener.time, "time", lambda: 1787585449)

    def download(file_id: str, destination: str) -> bool:
        order.append("download")
        assert file_id == "telegram-file-1"
        assert destination.endswith("ticket_1787585449.jpg")
        return True

    def forward(file_id: str, caption: str) -> None:
        order.append("forward")
        assert file_id == "telegram-file-1"
        assert caption == "Ganado"

    def reply(chat_id: int, text: str) -> None:
        order.append("reply")
        assert chat_id == ADMIN_ID
        assert "ticket_1787585449.jpg" in text

    monkeypatch.setattr(ticket_listener, "download_photo", download)
    monkeypatch.setattr(ticket_listener, "reenviar_a_canal", forward)
    monkeypatch.setattr(ticket_listener, "responder", reply)
    update = {
        "message": {
            "chat": {"id": ADMIN_ID},
            "caption": "Ganado",
            "photo": [
                {"file_id": "small", "file_unique_id": "unique-small"},
                {
                    "file_id": "telegram-file-1",
                    "file_unique_id": "unique-photo-1",
                },
            ],
        }
    }

    ticket_listener.procesar_foto(update)

    assert order == ["download", "insert", "forward", "reply"]
    assert fake_supabase.table_name == "tickets_ganadores"
    assert fake_supabase.inserted["telegram_chat_id"] == ADMIN_ID
    assert fake_supabase.inserted["file_unique_id"] == "unique-photo-1"
    received_at = datetime.fromisoformat(str(fake_supabase.inserted["received_at"]))
    assert received_at.utcoffset() is not None
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8")) == [
        "ticket_1787585449.jpg"
    ]


@dataclass
class HttpResponse:
    status_code: int
    content: bytes = b""
    chunks: tuple[bytes, ...] = ()
    closed: bool = False

    def iter_content(self, chunk_size: int):
        assert chunk_size == 64 * 1024
        yield from self.chunks

    def close(self) -> None:
        self.closed = True


class FakeTelegramSession:
    def __init__(self, *, metadata: object, download: HttpResponse):
        self.metadata = metadata
        self.download = download
        self.post_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []

    def post(
        self,
        url: str,
        *,
        data: dict[str, str],
        timeout: int,
        stream: bool,
        allow_redirects: bool,
    ):
        self.post_calls.append(
            {
                "url": url,
                "data": data,
                "timeout": timeout,
                "stream": stream,
                "allow_redirects": allow_redirects,
            }
        )
        raw = json.dumps({"ok": True, "result": self.metadata}).encode("utf-8")
        return HttpResponse(
            200,
            chunks=(raw[:17], raw[17:]),
        )

    def get(
        self,
        url: str,
        *,
        timeout: int,
        stream: bool,
        allow_redirects: bool,
    ):
        self.get_calls.append(
            {
                "url": url,
                "timeout": timeout,
                "stream": stream,
                "allow_redirects": allow_redirects,
            }
        )
        return self.download


def test_fetcher_uses_get_file_then_exact_telegram_file_host(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = jpeg_bytes()
    download = HttpResponse(200, chunks=(raw[:29], raw[29:]))
    session = FakeTelegramSession(
        metadata={"file_path": "photos/ticket_1.jpg"}, download=download
    )

    with caplog.at_level(logging.DEBUG):
        data = TelegramTicketFetcher("bot-secret", session=session).fetch("file-1")

    assert data == raw
    assert session.post_calls == [
        {
            "url": "https://api.telegram.org/botbot-secret/getFile",
            "data": {"file_id": "file-1"},
            "timeout": 30,
            "stream": True,
            "allow_redirects": False,
        }
    ]
    assert session.get_calls == [
        {
            "url": (
                "https://api.telegram.org/file/botbot-secret/photos/ticket_1.jpg"
            ),
            "timeout": 30,
            "stream": True,
            "allow_redirects": False,
        }
    ]
    assert download.closed
    assert "bot-secret" not in caplog.text


@pytest.mark.parametrize(
    ("metadata", "download", "message"),
    [
        ({"file_path": "../secret"}, HttpResponse(200), "path"),
        ({"file_path": "documents/ticket.jpg"}, HttpResponse(200), "path"),
        (
            {"file_path": "photos/ticket.jpg"},
            HttpResponse(500, chunks=()),
            "download",
        ),
        (
            {"file_path": "photos/ticket.jpg"},
            HttpResponse(200, chunks=(b"not jpeg",)),
            "download",
        ),
        (
            {"file_path": "photos/ticket.jpg"},
            HttpResponse(200, chunks=(b"\xff\xd8" + b"x" * (10 * 1024 * 1024),)),
            "download",
        ),
    ],
    ids=("traversal", "wrong-directory", "network", "malformed", "oversized"),
)
def test_fetcher_rejects_unsafe_or_invalid_downloads(
    metadata: object, download: HttpResponse, message: str
) -> None:
    session = FakeTelegramSession(metadata=metadata, download=download)

    with pytest.raises(RuntimeError, match=message):
        TelegramTicketFetcher("bot-secret", session=session).fetch("file-1")


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json",
        json.dumps({"ok": False, "result": {}}).encode("utf-8"),
        b"x" * (256 * 1024 + 1),
    ],
    ids=("malformed-json", "telegram-error", "oversized-json"),
)
def test_fetcher_rejects_invalid_bounded_metadata(raw: bytes) -> None:
    class MetadataSession(FakeTelegramSession):
        def post(
            self,
            url: str,
            *,
            data: dict[str, str],
            timeout: int,
            stream: bool,
            allow_redirects: bool,
        ):
            assert stream is True
            return HttpResponse(200, chunks=(raw,))

    session = MetadataSession(metadata={}, download=HttpResponse(200))

    with pytest.raises(RuntimeError, match=r"^Telegram file metadata failed$"):
        TelegramTicketFetcher("bot-secret", session=session).fetch("file-1")

    assert session.get_calls == []


def test_fetcher_sanitizes_network_exception_and_never_logs_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class NetworkSession:
        def post(
            self,
            url: str,
            *,
            data: dict[str, str],
            timeout: int,
            stream: bool,
            allow_redirects: bool,
        ):
            raise RuntimeError("bot-secret upstream body")

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(
            RuntimeError, match=r"^Telegram file metadata failed$"
        ) as raised:
            TelegramTicketFetcher(
                "bot-secret", session=NetworkSession()
            ).fetch("file-1")

    assert raised.value.__cause__ is None
    assert "bot-secret" not in caplog.text


@pytest.mark.parametrize(
    "private_text",
    [
        "Saldo 1200 Carlos 5551234567",
        "Nombre Carlos Gutiérrez",
        "Dirección Av. Reforma 123",
        "Contacto 55 5123 4567",
        "Referencia 012180015228133759",
        "Pago a carlos@example.com",
    ],
)
def test_privacy_terms_force_pending_review(private_text: str) -> None:
    report = final_report()
    result = EvidenceInspector(
        ocr=lambda _: (
            f"{private_text} Aryans Sports 5-0 Nbp Rainbow AC "
            "ID: 5329224423"
        )
    ).inspect(jpeg_bytes(), report=report)

    assert result.state == "pending_review"
    assert result.ticket_id == ""
    assert result.pick_ids == ()


def test_exact_team_and_score_match_preserves_full_ticket_id() -> None:
    report = final_report()
    result = EvidenceInspector(
        ocr=lambda _: "Aryans Sports 5-0 Nbp Rainbow AC ID: 5329224423"
    ).inspect(jpeg_bytes(), report=report)

    assert result.state == "matched"
    assert result.ticket_id == "5329224423"
    assert result.pick_ids == (101,)


def test_inspector_accepts_a_truthful_multi_pick_ticket() -> None:
    report = final_report()
    result = EvidenceInspector(
        ocr=lambda _: (
            "Aryans Sports 5-0 Nbp Rainbow AC "
            "Kalighat MS 0-2 East Bengal II ID: 5329224423"
        )
    ).inspect(jpeg_bytes(), report=report)

    assert result.state == "matched"
    assert result.pick_ids == (101, 102)


@pytest.mark.parametrize(
    "text",
    [
        "Aryans Sports 5-1 Nbp Rainbow AC ID: 5329224423",
        "Aryans Sports 5-0 Another Club ID: 5329224423",
        "Aryans Sports 5-0 Nbp Rainbow AC",
        "Aryans Sports 5-0 Nbp Rainbow AC ID: 12345",
    ],
)
def test_inspector_fails_closed_for_nonexact_or_missing_identity(text: str) -> None:
    result = EvidenceInspector(ocr=lambda _: text).inspect(
        jpeg_bytes(), report=final_report()
    )

    assert result.state == "pending_review"
    assert result.pick_ids == ()


def test_inspector_marks_tesseract_failure_pending_without_raw_error() -> None:
    def failed_ocr(_: bytes) -> str:
        raise RuntimeError("OCR raw Saldo 1200")

    result = EvidenceInspector(ocr=failed_ocr).inspect(
        jpeg_bytes(), report=final_report()
    )

    assert result == EvidenceDecision(
        "pending_review", "", (), sha256(b"").hexdigest()
    )


def test_inspector_marks_malformed_jpeg_pending_before_ocr() -> None:
    called = False

    def ocr(_: bytes) -> str:
        nonlocal called
        called = True
        return "Aryans Sports 5-0 Nbp Rainbow AC ID: 5329224423"

    result = EvidenceInspector(ocr=ocr).inspect(
        b"not-jpeg", report=final_report()
    )

    assert not called
    assert result.state == "pending_review"
    assert result.pick_ids == ()


def test_tesseract_wrapper_opens_real_jpeg_and_requests_spanish_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[int, int], str, str]] = []

    def fake_ocr(image: Image.Image, *, lang: str) -> str:
        calls.append((image.size, image.mode, lang))
        return "texto"

    monkeypatch.setattr("backend.ticket_evidence.pytesseract.image_to_string", fake_ocr)

    assert tesseract_ocr(jpeg_bytes()) == "texto"
    assert calls == [((640, 960), "RGB", "spa+eng")]


class EvidenceRepositoryFake:
    def __init__(self, candidate: TicketCandidate):
        self.candidate = candidate
        self.records: list[tuple[TicketCandidate, EvidenceDecision, str]] = []

    def candidates(self, *, portfolio_date: str):
        assert portfolio_date == "2026-08-24"
        return (self.candidate,)

    def record(
        self,
        *,
        candidate: TicketCandidate,
        report: ResultReport,
        decision: EvidenceDecision,
        media_digest: str,
    ) -> None:
        assert report is final_report_instance
        self.records.append((candidate, decision, media_digest))


final_report_instance = final_report()


def test_collection_records_safe_pending_review_on_fetch_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    candidate = TicketCandidate(
        "unique-photo-1", "file-1", "unique-photo-1", "2026-08-24T08:00:00Z"
    )
    repository = EvidenceRepositoryFake(candidate)

    class Fetcher:
        def fetch(self, file_id: str) -> bytes:
            raise RuntimeError("raw OCR Saldo 1200 bot-secret")

    with caplog.at_level(logging.WARNING):
        result = collect_matched_evidence(
            final_report_instance,
            repository=repository,
            fetcher=Fetcher(),  # type: ignore[arg-type]
            inspector=EvidenceInspector(ocr=lambda _: "unused"),
        )

    assert result == ()
    assert repository.records[0][1].state == "pending_review"
    assert repository.records[0][1].ticket_id == ""
    assert repository.records[0][1].ocr_digest == sha256(b"").hexdigest()
    assert "Saldo" not in caplog.text
    assert "bot-secret" not in caplog.text


def test_collection_returns_only_matched_evidence() -> None:
    candidate = TicketCandidate(
        "unique-photo-1", "file-1", "unique-photo-1", "2026-08-24T08:00:00Z"
    )
    repository = EvidenceRepositoryFake(candidate)
    raw = jpeg_bytes()

    class Fetcher:
        def fetch(self, file_id: str) -> bytes:
            assert file_id == "file-1"
            return raw

    result = collect_matched_evidence(
        final_report_instance,
        repository=repository,
        fetcher=Fetcher(),  # type: ignore[arg-type]
        inspector=EvidenceInspector(
            ocr=lambda _: "Aryans Sports 5-0 Nbp Rainbow AC ID: 5329224423"
        ),
    )

    assert len(result) == 1
    assert result[0].evidence_id == "unique-photo-1"
    assert result[0].ticket_id == "5329224423"
    assert result[0].pick_ids == (101,)
    assert result[0].jpeg == raw
    assert repository.records[0][2] == sha256(raw).hexdigest()


def test_local_collection_uses_manifest_jpegs_without_exposing_file_paths(tmp_path) -> None:
    tickets = tmp_path / "tickets"
    tickets.mkdir()
    raw = jpeg_bytes()
    (tickets / "ticket_1787585449.jpg").write_bytes(raw)
    (tickets / "manifest.json").write_text(
        json.dumps(["ticket_1787585449.jpg"]), encoding="utf-8"
    )

    result = collect_local_matched_evidence(
        final_report_instance,
        tickets_dir=tickets,
        inspector=EvidenceInspector(
            ocr=lambda _: "Aryans Sports 5-0 Nbp Rainbow AC ID: 5329224423"
        ),
    )

    assert len(result) == 1
    assert result[0].evidence_id == "ticket_1787585449.jpg"
    assert result[0].ticket_id == "5329224423"
    assert result[0].jpeg == raw
