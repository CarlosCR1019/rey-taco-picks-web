import ast
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

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


def test_fallback_uses_only_named_moneylines_and_has_no_minimum_pick_fabrication():
    text = SCRAPER.read_text(encoding="utf-8")
    assert "named_prices.get('home')" in text
    assert "if len(picks_fallback) < 3" not in text


def test_phase7_delegates_persistence_and_delivery_without_legacy_side_effects():
    tree = ast.parse(SCRAPER.read_text(encoding="utf-8"))
    phase = _top_level_function(tree, "fase7_guardar_y_notificar")
    called_names = {
        node.func.id
        for node in ast.walk(phase)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "publish_batch" in called_names
    assert "deliver_batch" in called_names
    assert not {"open", "urlopen", "_guardar_local", "_enviar_telegram"} & called_names

    function_names = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert "_guardar_local" not in function_names
    assert "_enviar_telegram" not in function_names


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
        }

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
        }
    ]


class HashGuardRepository(FakeRepository):
    def __init__(self):
        super().__init__()
        self.run_hashes = {}
        self.batch_count = 0

    def publish(self, run_key, source_hash, picks):
        self.published.append((run_key, source_hash, list(picks)))
        previous_hash = self.run_hashes.get(run_key)
        if previous_hash is not None and previous_hash != source_hash:
            raise RuntimeError("SQL rejected a reused run key with a different hash")
        if previous_hash is None:
            self.run_hashes[run_key] = source_hash
            self.batch_count += 1
        return {
            "run_id": "run-1",
            "batch_id": "batch-1",
            "created": previous_hash is None,
            "delivery_status": {},
        }


def test_github_run_id_is_stable_across_reruns_and_source_hash_stays_separate(tmp_path):
    from backend.scraper import PersistenceFailure, fase7_guardar_y_notificar

    repository = HashGuardRepository()
    sent = []

    def transport(destination, text):
        sent.append((destination.name, text))

    fase7_guardar_y_notificar(
        single_pick("Pumas gana"),
        repository=repository,
        settings=scraper_settings(tmp_path),
        transport=transport,
        run_key="github-run:424242",
    )
    sent_after_first_run = list(sent)

    with pytest.raises(PersistenceFailure, match="scraper batch persistence failed"):
        fase7_guardar_y_notificar(
            single_pick("Atlas gana"),
            repository=repository,
            settings=scraper_settings(tmp_path),
            transport=transport,
            run_key="github-run:424242",
        )

    assert [attempt[0] for attempt in repository.published] == [
        "github-run:424242",
        "github-run:424242",
    ]
    assert repository.published[0][1] != repository.published[1][1]
    assert repository.batch_count == 1
    assert sent == sent_after_first_run


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

    picks = [
        {
            "partido": "Pumas vs Atlas",
            "pick": "Pumas gana",
            "cuota": "1.80",
            "confianza": "85%",
            "razonamiento": "Razonamiento público que no debe filtrarse",
            "es_parlay": False,
        },
        {
            "partido": "Toluca vs América",
            "pick": "PREMIUM SECRET",
            "cuota": "2.10",
            "confianza": "82%",
            "razonamiento": "Análisis VIP",
            "es_parlay": False,
        },
    ]

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
