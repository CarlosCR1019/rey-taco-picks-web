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
