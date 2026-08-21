import ast
import json
import os
from pathlib import Path
import subprocess
import sys

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


def test_fallback_uses_the_function_argument_not_an_undefined_global():
    text = SCRAPER.read_text(encoding="utf-8")
    assert "if len(picks_fallback) < 3 and partidos_data:" in text
    assert "for p in partidos_data:" in text


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
    environment.pop("SUPABASE_URL", None)
    environment.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    completed = subprocess.run(
        [sys.executable, str(SCRAPER)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )

    assert completed.returncode != 0
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


def test_phase7_public_projection_redacts_reasoning_and_premium_picks(tmp_path):
    from backend.scraper import fase7_guardar_y_notificar

    public_path = tmp_path / "public" / "picks.json"
    settings = ScraperSettings(
        dry_run=False,
        supabase_url="https://example.supabase.co",
        service_role_key="service-role",
        groq_api_key="",
        odds_api_key="",
        telegram_token="telegram-token",
        telegram_admin_id="admin-id",
        telegram_vip_id="vip-id",
        telegram_free_id="free-id",
        public_picks_path=public_path,
        queue_path=tmp_path / "unused-legacy-queue.json",
    )
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
