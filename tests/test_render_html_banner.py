from datetime import datetime
from pathlib import Path
import subprocess
import sys

from backend import render_html_banner, social_banner
from backend.render_html_banner import build_cards_html


ROOT = Path(__file__).resolve().parents[1]


def _pick(*, has_value: bool) -> dict[str, object]:
    return {
        "categoria": "Liga MX",
        "partido": "América vs Tigres",
        "pick": "América",
        "cuota": 1.80,
        "confianza": "65% respaldo de datos",
        "riesgo": "Datos limitados",
        "tiene_valor": has_value,
        "horario": "Hoy 20:00 hrs",
    }


def test_limited_data_banner_does_not_claim_value():
    html = build_cards_html([_pick(has_value=False)])

    assert "Respaldo de datos: 65%" in html
    assert "Respaldo de datos: 65% respaldo de datos" not in html
    assert "Datos limitados" in html
    assert "Señal de valor" not in html
    assert "+EV" not in html


def test_banner_only_shows_value_signal_for_source_backed_true_value():
    html = build_cards_html([_pick(has_value=True)])

    assert "Señal de valor" in html
    assert "+EV" not in html


def test_banner_template_has_no_unconditional_positive_value_claim():
    template = (ROOT / "backend" / "banner_template.html").read_text(
        encoding="utf-8"
    )

    assert "+EV" not in template


def test_banner_dates_use_dynamic_spanish_months():
    september = datetime(2026, 9, 3, 12, 0)

    assert render_html_banner.banner_date_label(september) == (
        "03 DE SEPTIEMBRE, 2026 • CDMX"
    )
    assert social_banner.banner_date_label(september) == (
        "03 DE SEPTIEMBRE, 2026 • CDMX"
    )
    render_source = (ROOT / "backend" / "render_html_banner.py").read_text(
        encoding="utf-8"
    )
    social_source = (ROOT / "backend" / "social_banner.py").read_text(
        encoding="utf-8"
    )
    assert "%d DE AGOSTO" not in render_source.upper()
    assert "%d DE AGOSTO" not in social_source.upper()


def test_social_and_html_banner_modules_resolve_from_repository_root():
    probe = (
        "import runpy; "
        "runpy.run_module('backend.render_html_banner', run_name='render_probe'); "
        "runpy.run_module('backend.social_poster', run_name='social_probe')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr


def test_social_workflow_runs_package_module_from_repository_root():
    workflow = (ROOT / ".github" / "workflows" / "scraper.yml").read_text(
        encoding="utf-8"
    )
    social_step = workflow[workflow.index("Auto-Post Social Media Banner"):]

    assert "python -m backend.social_poster" in social_step
    assert "cd backend" not in social_step
