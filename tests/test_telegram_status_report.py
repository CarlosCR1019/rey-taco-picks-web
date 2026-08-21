from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "send_telegram_status_report.py"


class _FakeQuery:
    def table(self, *_args, **_kwargs):
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


def _load_report_module_without_network():
    dotenv = ModuleType("dotenv")
    dotenv.load_dotenv = lambda *_args, **_kwargs: None
    supabase = ModuleType("supabase")
    supabase.create_client = lambda *_args, **_kwargs: _FakeQuery()
    spec = spec_from_file_location("status_report_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    with (
        patch.dict(os.environ, {}, clear=True),
        patch.dict(sys.modules, {"dotenv": dotenv, "supabase": supabase}),
        patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")),
    ):
        spec.loader.exec_module(module)
    return module


def test_status_report_uses_real_count_and_neutral_language_without_network():
    module = _load_report_module_without_network()
    rows = [
        {
            "partido": "América vs Tigres",
            "pick": "América",
            "cuota": 1.80,
            "confianza": "65% respaldo de datos",
            "tiene_valor": False,
        },
        {
            "partido": "Pumas vs Atlas",
            "pick": "Menos de 2.5",
            "cuota": 1.90,
            "confianza": "85% respaldo de datos",
            "tiene_valor": True,
        },
    ]

    message = module.build_status_message(rows, generated_at="08:00 PM CDMX")

    assert "2 registros pendientes recuperados" in message
    assert "15 jugadas" not in message
    assert "+EV" not in message


def test_status_report_does_not_present_limited_query_size_as_total_found():
    module = _load_report_module_without_network()
    rows = [
        {
            "partido": f"Evento {index}",
            "pick": "Local",
            "cuota": 1.80,
            "confianza": "65% respaldo de datos",
            "tiene_valor": False,
        }
        for index in range(module.REPORT_LIMIT)
    ]

    message = module.build_status_message(rows, generated_at="08:00 PM CDMX")

    assert "10 jugadas pendientes encontradas" not in message
    assert "10 registros pendientes recuperados (consulta limitada a 10)" in message


def test_status_report_shows_value_signal_only_on_explicit_true_row():
    module = _load_report_module_without_network()
    rows = [
        {
            "partido": "Sin valor vs Rival",
            "pick": "Local",
            "cuota": 1.80,
            "confianza": "65% respaldo de datos",
            "tiene_valor": False,
        },
        {
            "partido": "Con valor vs Rival",
            "pick": "Visitante",
            "cuota": 1.90,
            "confianza": "85% respaldo de datos",
            "tiene_valor": True,
        },
    ]

    message = module.build_status_message(rows, generated_at="08:00 PM CDMX")
    lines = message.splitlines()
    false_line = next(line for line in lines if "Sin valor vs Rival" in line)
    true_line = next(line for line in lines if "Con valor vs Rival" in line)

    assert "Señal de valor" not in false_line
    assert "Respaldo de datos: 65%" in false_line
    assert "Señal de valor comparada" in true_line
    assert "Respaldo de datos: 85%" in true_line
