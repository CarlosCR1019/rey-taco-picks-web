from pathlib import Path

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
