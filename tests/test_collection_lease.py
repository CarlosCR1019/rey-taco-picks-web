import pytest

from backend.collection_lease import (
    CollectionLeaseClient,
    collection_window_key,
    run_cli,
)


class Response:
    def __init__(self, data):
        self.data = data


class Rpc:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return Response(self.response)


class Client:
    def __init__(self, response=True, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def rpc(self, name, arguments):
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        return Rpc(self.response)


def test_window_key_is_stable_for_schedule_and_bounded_for_manual():
    assert collection_window_key(
        portfolio_date="2026-08-23",
        event_name="schedule",
        schedule="0 22 * * *",
        run_id="99",
    ) == "2026-08-23|schedule|0 22 * * *"
    assert collection_window_key(
        portfolio_date="2026-08-23",
        event_name="workflow_dispatch",
        schedule="",
        run_id="99",
    ) == "2026-08-23|manual|99"


@pytest.mark.parametrize(
    "arguments",
    [
        {"portfolio_date": "bad", "event_name": "schedule", "schedule": "0 22 * * *", "run_id": "1"},
        {"portfolio_date": "2026-08-23", "event_name": "push", "schedule": "", "run_id": "1"},
        {"portfolio_date": "2026-08-23", "event_name": "schedule", "schedule": "", "run_id": "1"},
        {"portfolio_date": "2026-08-23", "event_name": "workflow_dispatch", "schedule": "", "run_id": ""},
    ],
)
def test_window_key_rejects_ambiguous_identity(arguments):
    with pytest.raises((TypeError, ValueError)):
        collection_window_key(**arguments)


def test_client_claims_exact_window_owner_and_bounded_expiration():
    repository = Client(True)
    lease = CollectionLeaseClient(repository)

    assert lease.claim("2026-08-23|schedule|0 22 * * *", "residential:42") is True
    assert repository.calls == [(
        "claim_residential_collection_lease",
        {
            "requested_window_key": "2026-08-23|schedule|0 22 * * *",
            "requested_owner_run_key": "residential:42",
            "requested_lease_minutes": 30,
        },
    )]


@pytest.mark.parametrize("response", [None, 1, "true", {}, []])
def test_client_fails_closed_on_malformed_claim_response(response):
    with pytest.raises(RuntimeError, match="invalid response"):
        CollectionLeaseClient(Client(response)).claim(
            "2026-08-23|manual|42", "residential:42"
        )


def test_client_rejects_invalid_contract_before_rpc():
    repository = Client(True)
    lease = CollectionLeaseClient(repository)
    with pytest.raises((TypeError, ValueError)):
        lease.claim("", "residential:42")
    with pytest.raises((TypeError, ValueError)):
        lease.claim("2026-08-23|manual|42", "", lease_minutes=30)
    with pytest.raises((TypeError, ValueError)):
        lease.claim("2026-08-23|manual|42", "residential:42", lease_minutes=61)
    assert repository.calls == []


def test_client_releases_only_the_exact_window_owner():
    repository = Client(True)

    assert CollectionLeaseClient(repository).release(
        "2026-08-23|schedule|0 22 * * *", "holder:unique-nonce"
    ) is True
    assert repository.calls == [(
        "release_residential_collection_lease",
        {
            "requested_window_key": "2026-08-23|schedule|0 22 * * *",
            "requested_owner_run_key": "holder:unique-nonce",
        },
    )]


def _values():
    return {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "COLLECTION_LEASE_OWNER_KEY": "residential:42:primary:unique-nonce",
    }


@pytest.mark.parametrize(
    ("response", "code", "line"),
    [
        (True, 0, "collection_lease=acquired"),
        (False, 3, "collection_lease=busy"),
    ],
)
def test_cli_emits_only_bounded_claim_outcome(response, code, line, capsys):
    result = run_cli(
        ["--window-key", "2026-08-23|schedule|0 22 * * *"],
        values=_values(),
        client_factory=lambda _url, _key: Client(response),
    )

    assert result == code
    captured = capsys.readouterr()
    assert captured.out.strip() == line
    assert captured.err == ""


def test_cli_masks_configuration_and_provider_failures(capsys):
    assert run_cli([], values=_values()) == 2
    assert capsys.readouterr().out.strip() == "collection_lease=invalid"

    assert run_cli(
        ["--window-key", "2026-08-23|manual|42"],
        values={},
    ) == 2
    assert capsys.readouterr().out.strip() == "collection_lease=invalid"

    assert run_cli(
        ["--window-key", "2026-08-23|manual|42"],
        values=_values(),
        client_factory=lambda _url, _key: Client(error=RuntimeError("secret body")),
    ) == 2
    assert capsys.readouterr().out.strip() == "collection_lease=invalid"


def test_configuration_error_never_contains_secret_values(capsys):
    assert run_cli(
        ["--window-key", "2026-08-23|manual|42"],
        values={"SUPABASE_SERVICE_ROLE_KEY": "top-secret"},
    ) == 2
    captured = capsys.readouterr()
    assert captured.out.strip() == "collection_lease=invalid"
    assert "top-secret" not in captured.out + captured.err


@pytest.mark.parametrize(
    ("response", "code", "line"),
    [
        (True, 0, "collection_lease=released"),
        (False, 3, "collection_lease=not_owner"),
    ],
)
def test_cli_release_is_owner_bounded(response, code, line, capsys):
    result = run_cli(
        ["--window-key", "2026-08-23|manual|42", "--release"],
        values=_values(),
        client_factory=lambda _url, _key: Client(response),
    )

    assert result == code
    assert capsys.readouterr().out.strip() == line
