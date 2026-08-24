from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "send_telegram_status_report.py"


class _FakeQuery:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.calls = []

    def table(self, *_args, **_kwargs):
        self.calls.append(("table", _args))
        return self

    def select(self, *_args, **_kwargs):
        self.calls.append(("select", _args))
        return self

    def eq(self, *_args, **_kwargs):
        self.calls.append(("eq", _args))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


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


def test_status_query_requires_active_pending_rows():
    module = _load_report_module_without_network()
    database = _FakeQuery()

    assert module._active_picks(database) == []
    assert ("eq", ("active", True)) in database.calls
    assert ("eq", ("estado", "pendiente")) in database.calls


def test_main_sends_full_active_batch_to_private_vip_and_only_public_to_free():
    module = _load_report_module_without_network()
    rows = [
        {
            "partido": "América vs Tigres",
            "pick": "PUBLIC PICK",
            "cuota": 1.8,
            "confianza": "65%",
            "visibility": "public",
            "razonamiento": "PUBLIC RATIONALE MUST NOT LEAK",
        },
        {
            "partido": "Pumas vs Atlas",
            "pick": "PREMIUM SECRET",
            "cuota": 2.1,
            "confianza": "85%",
            "visibility": "premium",
            "razonamiento": "PREMIUM RATIONALE",
        },
    ]
    database = _FakeQuery(rows)
    sent = []
    module.create_client = lambda *_args: database
    module._send_message = lambda _token, chat_id, message: sent.append(
        (chat_id, message)
    ) or 200

    with patch.dict(os.environ, {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "TELEGRAM_BOT_TOKEN": "bot-token",
        "TELEGRAM_CHAT_ID": "admin-chat",
        "TELEGRAM_VIP_CHANNEL_ID": "vip-chat",
        "TELEGRAM_FREE_CHANNEL_ID": "free-chat",
    }, clear=True):
        assert module.main() == 0

    messages = dict(sent)
    assert "PREMIUM SECRET" in messages["admin-chat"]
    assert "PREMIUM SECRET" in messages["vip-chat"]
    assert "PREMIUM SECRET" not in messages["free-chat"]
    assert "PUBLIC PICK" in messages["free-chat"]
    assert "RATIONALE" not in messages["free-chat"]
