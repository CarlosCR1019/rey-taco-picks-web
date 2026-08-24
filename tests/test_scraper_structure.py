import ast
from datetime import datetime
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from backend.pick_publisher import PERSISTED_PICK_COLUMNS
from backend.scraper_config import ScraperSettings


SCRAPER = Path(__file__).resolve().parents[1] / "backend" / "scraper.py"
REPO_ROOT = SCRAPER.parents[1]


def _top_level_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_scraper_has_no_duplicate_top_level_functions():
    tree = ast.parse(SCRAPER.read_text(encoding="utf-8"))
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert len(names) == len(set(names))


def test_phase6_has_no_deterministic_pick_fallback_or_minimum_fabrication():
    text = SCRAPER.read_text(encoding="utf-8")
    assert "validate_ai_ranking" in text
    assert "picks_fallback" not in text
    assert "named_prices.get('home')" not in text
    assert "if len(picks_fallback) < 3" not in text


def test_phase7_delegates_persistence_and_delivery_without_legacy_side_effects():
    tree = ast.parse(SCRAPER.read_text(encoding="utf-8"))
    phase = _top_level_function(tree, "fase7_guardar_y_notificar")
    called_names = {
        node.func.id
        for node in ast.walk(phase)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "AuditedBatchPublisher" in called_names
    delivery = _top_level_function(tree, "_deliver_persisted_publication")
    delivery_calls = {
        node.func.id
        for node in ast.walk(delivery)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "_deliver_persisted_publication" in called_names
    assert "deliver_batch" in delivery_calls
    assert not {"open", "urlopen", "_guardar_local", "_enviar_telegram"} & called_names

    function_names = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert "_guardar_local" not in function_names
    assert "_enviar_telegram" not in function_names


def test_workflow_delivers_resumed_batches_only_from_cloud():
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "collector.yml"
    ).read_text(encoding="utf-8")

    assert "--collect-only" in workflow
    assert "--deliver-only" in workflow
    assert "deliver_cloud" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "python -m backend.social_poster" in workflow
    assert "residential:${{ github.run_id }}" in workflow


def test_scraper_script_can_import_extracted_publishers_from_repo_root():
    environment = dict(os.environ)
    for name in (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_KEY",
        "GROQ_API_KEY",
        "ODDS_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_VIP_CHANNEL_ID",
        "TELEGRAM_CHANNEL_ID",
        "TELEGRAM_FREE_CHANNEL_ID",
        "SCRAPER_RUN_KEY",
        "GITHUB_RUN_ID",
    ):
        environment.pop(name, None)
    environment["PYTHON_DOTENV_DISABLED"] = "1"
    probe = (
        "import runpy, sys; "
        "namespace = runpy.run_path(sys.argv[1], run_name='scraper_import_probe'); "
        "assert namespace['__name__'] == 'scraper_import_probe'; "
        "assert callable(namespace.get('main'))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(SCRAPER)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr


class FakeRepository:
    def __init__(self):
        self.published = []
        self.deliveries = []

    def publish(self, run_key, source_hash, picks):
        self.published.append((run_key, source_hash, list(picks)))
        return {
            "run_id": "run-1",
            "batch_id": "batch-1",
            "created": True,
            "delivery_status": {},
            "picks": stored_rows(picks),
        }

    def resume(self, _run_key):
        return None

    def record_delivery(self, run_id, destination, success, error=""):
        self.deliveries.append((run_id, destination, success, error))


def scraper_settings(tmp_path, *, token="telegram-token"):
    return ScraperSettings(
        dry_run=False,
        run_key="test-run",
        supabase_url="https://example.supabase.co",
        service_role_key="service-role",
        groq_api_key="",
        odds_api_key="",
        telegram_token=token,
        telegram_admin_id="admin-id",
        telegram_vip_id="vip-id",
        telegram_free_id="free-id",
        public_picks_path=tmp_path / "public" / "picks.json",
        queue_path=tmp_path / "unused-legacy-queue.json",
    )


def single_pick(selection):
    return [
        {
            "partido": "Pumas vs Atlas",
            "pick": selection,
            "cuota": "1.80",
            "confianza": "85%",
            "razonamiento": "Análisis privado",
            "es_parlay": False,
            "source": "the-odds-api",
            "source_event_id": "event-pumas-atlas",
            "source_market_key": "h2h|full_time|",
            "source_selection_key": "home",
            "source_observed_at": "2026-08-20T20:00:00Z",
            "source_starts_at": "2099-08-21T01:00:00Z",
        }
    ]


def six_distinct_picks():
    rows = []
    for index in range(6):
        row = dict(single_pick(f"Pick {index}")[0])
        row.update(
            {
                "partido": f"Home {index} vs Away {index}",
                "source_event_id": f"event-{index}",
                "source_selection_key": f"selection-{index}",
                "source_starts_at": f"2099-08-2{index + 1}T01:00:00Z",
            }
        )
        rows.append(row)
    return rows


def stored_rows(picks):
    result = []
    for index, pick in enumerate(picks, start=1):
        row = {column: pick.get(column) for column in PERSISTED_PICK_COLUMNS}
        row["id"] = index
        if row["visibility"] == "public":
            row["razonamiento"] = None
        result.append(row)
    return result


class ReplayRepository(FakeRepository):
    def __init__(self):
        super().__init__()
        self.persisted = None
        self.delivery_status = {}
        self.batch_count = 0

    def publish(self, run_key, source_hash, picks):
        self.published.append((run_key, source_hash, list(picks)))
        created = self.persisted is None
        if created:
            self.persisted = stored_rows(picks)
            self.batch_count += 1
        return {
            "run_id": "run-1",
            "batch_id": "batch-1",
            "created": created,
            "delivery_status": dict(self.delivery_status),
            "picks": self.persisted,
        }

    def record_delivery(self, run_id, destination, success, error=""):
        super().record_delivery(run_id, destination, success, error)
        self.delivery_status[destination] = {"success": success, "error": error}


def test_phase7_accepts_six_picks_with_two_distinct_public_rows(tmp_path):
    from backend.scraper import fase7_guardar_y_notificar

    repository = FakeRepository()

    publication, deliveries = fase7_guardar_y_notificar(
        six_distinct_picks(),
        repository=repository,
        settings=scraper_settings(tmp_path),
        run_key="six-pick-run",
        deliver=False,
    )

    persisted = repository.published[0][2]
    public = [row for row in persisted if row["visibility"] == "public"]
    assert publication.run_id == "run-1"
    assert deliveries == {}
    assert len(public) == 2
    assert len({row["source_event_id"] for row in public}) == 2
    assert all(row["es_parlay"] is False for row in public)


def test_same_run_retry_uses_persisted_rows_and_only_missing_deliveries(tmp_path):
    from backend.scraper import fase7_guardar_y_notificar

    repository = ReplayRepository()

    def first_transport(destination, _text):
        if destination.name == "vip":
            raise RuntimeError("temporary Telegram failure")

    fase7_guardar_y_notificar(
        single_pick("Pumas gana"),
        repository=repository,
        settings=scraper_settings(tmp_path),
        transport=first_transport,
        run_key="github-run:424242",
    )
    retried = []

    publication, deliveries = fase7_guardar_y_notificar(
        single_pick("NEW ATLAS PICK MUST NOT ESCAPE"),
        repository=repository,
        settings=scraper_settings(tmp_path),
        transport=lambda destination, text: retried.append((destination.name, text)),
        run_key="github-run:424242",
    )

    assert [attempt[0] for attempt in repository.published] == [
        "github-run:424242",
        "github-run:424242",
    ]
    assert repository.published[0][1] != repository.published[1][1]
    assert repository.batch_count == 1
    assert publication.created is False
    assert [name for name, _text in retried] == ["vip"]
    assert "Pumas gana" in retried[0][1]
    assert "NEW ATLAS" not in retried[0][1]
    assert deliveries["admin"].skipped is True
    assert deliveries["free"].skipped is True
    public_rows = json.loads(
        scraper_settings(tmp_path).public_picks_path.read_text(encoding="utf-8")
    )
    assert [row["pick"] for row in public_rows] == ["Pumas gana"]


def test_phase7_uses_only_the_explicit_resolved_run_key(tmp_path, monkeypatch):
    from backend.scraper import fase7_guardar_y_notificar

    assert (
        inspect.signature(fase7_guardar_y_notificar).parameters["run_key"].default
        is inspect.Parameter.empty
    )
    monkeypatch.setenv("SCRAPER_RUN_KEY", "ambient-key")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    repository = FakeRepository()
    fase7_guardar_y_notificar(
        single_pick("Pumas gana"),
        repository=repository,
        settings=scraper_settings(tmp_path),
        transport=lambda _destination, _text: None,
        run_key="resolved-key",
    )

    assert repository.published[0][0] == "resolved-key"


def test_phase7_preserves_verified_event_date_across_midnight(tmp_path, monkeypatch):
    from backend import scraper

    class BeforeMidnight(datetime):
        @classmethod
        def now(cls, tz=None):
            current = datetime(2026, 8, 20, 23, 59, tzinfo=tz)
            return current

    monkeypatch.setattr(scraper, "datetime", BeforeMidnight)
    repository = FakeRepository()
    picks = single_pick("Pumas gana")
    picks[0].update({
        "fecha_evento": "2026-08-21",
        "horario": "Hoy 00:30 hrs",
    })

    scraper.fase7_guardar_y_notificar(
        picks,
        repository=repository,
        settings=scraper_settings(tmp_path),
        transport=lambda _destination, _text: None,
        run_key="midnight-run",
    )

    assert repository.published[0][2][0]["fecha_evento"] == "2026-08-21"


def test_phase7_fails_closed_without_a_stable_run_key(tmp_path, monkeypatch):
    from backend.scraper import fase7_guardar_y_notificar

    monkeypatch.setenv("SCRAPER_RUN_KEY", "ambient-key-must-not-be-read")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    repository = FakeRepository()
    with pytest.raises(RuntimeError, match="clave estable"):
        fase7_guardar_y_notificar(
            single_pick("Pumas gana"),
            repository=repository,
            settings=scraper_settings(tmp_path),
            transport=lambda _destination, _text: None,
            run_key=None,
        )

    assert repository.published == []


def test_missing_telegram_token_records_each_configured_destination_as_failed(tmp_path):
    from backend.scraper import fase7_guardar_y_notificar

    repository = FakeRepository()
    _publication, deliveries = fase7_guardar_y_notificar(
        single_pick("Pumas gana"),
        repository=repository,
        settings=scraper_settings(tmp_path, token=""),
        run_key="manual-key",
    )

    assert set(deliveries) == {"admin", "vip", "free"}
    assert all(not result.success for result in deliveries.values())
    assert {result.error for result in deliveries.values()} == {
        "missing_telegram_token"
    }
    assert repository.deliveries == [
        ("run-1", "admin", False, "missing_telegram_token"),
        ("run-1", "vip", False, "missing_telegram_token"),
        ("run-1", "free", False, "missing_telegram_token"),
    ]


class FirstRecordFailureRepository(FakeRepository):
    def __init__(self):
        super().__init__()
        self.record_attempts = []

    def record_delivery(self, run_id, destination, success, error=""):
        self.record_attempts.append((run_id, destination, success, error))
        if destination == "admin":
            raise RuntimeError("database password and arbitrary provider details")
        super().record_delivery(run_id, destination, success, error)


def test_delivery_record_failures_do_not_block_other_destinations_or_leak_errors(tmp_path):
    from backend.scraper import fase7_guardar_y_notificar

    repository = FirstRecordFailureRepository()
    with pytest.raises(RuntimeError) as captured:
        fase7_guardar_y_notificar(
            single_pick("Pumas gana"),
            repository=repository,
            settings=scraper_settings(tmp_path),
            transport=lambda _destination, _text: None,
            run_key="manual-key",
        )

    assert [attempt[1] for attempt in repository.record_attempts] == [
        "admin",
        "vip",
        "free",
    ]
    assert [delivery[1] for delivery in repository.deliveries] == ["vip", "free"]
    assert str(captured.value) == "No se pudieron registrar entregas de Telegram: admin"
    assert "password" not in str(captured.value)


def test_phase7_public_projection_redacts_reasoning_and_premium_picks(tmp_path):
    from backend.scraper import fase7_guardar_y_notificar

    public_path = tmp_path / "public" / "picks.json"
    settings = scraper_settings(tmp_path)
    repository = FakeRepository()
    sent = []

    def transport(destination, text):
        sent.append((destination.name, text))

    public_pick = single_pick("Pumas gana")[0]
    public_pick["razonamiento"] = "Razonamiento público que no debe filtrarse"
    premium_pick = single_pick("PREMIUM SECRET")[0]
    premium_pick.update({
        "partido": "Toluca vs América",
        "cuota": "2.10",
        "confianza": "82%",
        "razonamiento": "Análisis VIP",
        "source_event_id": "event-toluca-america",
        "source_selection_key": "away",
    })
    picks = [public_pick, premium_pick]

    publication, deliveries = fase7_guardar_y_notificar(
        picks,
        repository=repository,
        settings=settings,
        transport=transport,
        run_key="scheduled-2026-08-21",
    )

    assert publication.run_id == "run-1"
    assert set(deliveries) == {"admin", "vip", "free"}
    public_rows = json.loads(public_path.read_text(encoding="utf-8"))
    assert [row["pick"] for row in public_rows] == ["Pumas gana"]
    assert "razonamiento" not in public_rows[0]

    free_text = "\n".join(text for name, text in sent if name == "free")
    assert "PREMIUM SECRET" not in free_text
    assert "Razonamiento público" not in free_text
    assert {name for name, _text in sent} == {"admin", "vip", "free"}
    assert {destination for _run, destination, _success, _error in repository.deliveries} == {
        "admin",
        "vip",
        "free",
    }
