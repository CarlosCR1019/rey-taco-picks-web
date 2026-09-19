import backend.verificar_resultados as verifier
from backend.verificar_resultados import load_active_pending_picks


class _Response:
    data = [{"id": 42, "estado": "pendiente", "active": True}]


class _Query:
    def __init__(self):
        self.operations = []

    def select(self, fields):
        self.operations.append(("select", fields))
        return self

    def eq(self, field, value):
        self.operations.append(("eq", field, value))
        return self

    def execute(self):
        self.operations.append(("execute",))
        return _Response()


class _Client:
    def __init__(self):
        self.query = _Query()
        self.table_name = None

    def table(self, name):
        self.table_name = name
        return self.query


def test_result_verifier_reads_only_active_pending_picks():
    client = _Client()

    rows = load_active_pending_picks(client)

    assert rows == [{"id": 42, "estado": "pendiente", "active": True}]
    assert client.table_name == "picks"
    assert client.query.operations == [
        ("select", "*"),
        ("eq", "estado", "pendiente"),
        ("eq", "active", True),
        ("execute",),
    ]


class _ReadOnlyResponse:
    def __init__(self, data):
        self.data = data


class _ReadOnlyQuery:
    def __init__(self, client):
        self.client = client

    def select(self, _fields):
        return self

    def eq(self, _field, _value):
        return self

    def execute(self):
        return _ReadOnlyResponse(self.client.rows)

    def update(self, _decision):
        self.client.update_attempted = True
        raise AssertionError("dry-run attempted a Supabase update")


class _ReadOnlyClient:
    def __init__(self, rows):
        self.rows = rows
        self.update_attempted = False
        self.rpc_calls = []

    def table(self, _name):
        return _ReadOnlyQuery(self)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        raise AssertionError(f"dry-run attempted RPC {name}")


def test_result_verifier_dry_run_never_updates_or_publishes(monkeypatch):
    monkeypatch.setenv("RESULT_VERIFIER_DRY_RUN", "true")
    client = _ReadOnlyClient(
        [
            {
                "id": 42,
                "partido": "A vs B",
                "pick": "A",
                "fecha_evento": "2026-08-26",
            }
        ]
    )
    result_calls = []
    monkeypatch.setattr(verifier, "supabase", client)
    monkeypatch.setattr(
        verifier,
        "obtener_resultados_api",
        lambda *_args, **kwargs: result_calls.append(kwargs) or [object()],
    )
    monkeypatch.setattr(
        verifier,
        "grade_pending_pick_from_results",
        lambda *_args: {"estado": "ganado", "resultado_unidades": 1.0},
    )
    monkeypatch.setattr(
        verifier,
        "publish_available_result_reports",
        lambda: (_ for _ in ()).throw(AssertionError("dry-run attempted a report")),
    )

    verifier.verificar_picks()

    assert result_calls == [{"include_api_football": False}]
    assert client.update_attempted is False
    assert client.rpc_calls == []


def test_result_api_dry_run_skips_api_football_and_all_write_rpcs(monkeypatch):
    client = _ReadOnlyClient([])
    monkeypatch.setattr(verifier, "supabase", client)
    monkeypatch.setattr(verifier, "API_FOOTBALL_KEY", "test-key")
    monkeypatch.setattr(
        verifier.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline test")),
    )

    assert verifier.obtener_resultados_api(
        ["2026-08-26"],
        [{"partido": "A vs B", "fecha_evento": "2026-08-26"}],
        include_api_football=False,
    ) == []

    assert client.rpc_calls == []
