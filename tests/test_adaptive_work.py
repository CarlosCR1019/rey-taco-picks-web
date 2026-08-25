import json

import pytest

from backend.adaptive_work import AdaptiveWorkClient, run_cli


class Response:
    def __init__(self, payload, *, status=200):
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self, amount):
        return self._payload[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_client_posts_exact_date_to_service_role_rpc_without_query_secret():
    calls = []

    def opener(request, *, timeout):
        calls.append((request, timeout))
        return Response({
            "needs_collection": True,
            "lineup_due": True,
            "quote_due": False,
            "recoverable_due": False,
        })

    result = AdaptiveWorkClient(
        "https://example.supabase.co",
        "service-secret",
        opener=opener,
    ).status("2026-08-23")

    assert result.needs_collection is True
    request, timeout = calls[0]
    assert request.full_url == (
        "https://example.supabase.co/rest/v1/rpc/"
        "residential_adaptive_work_status"
    )
    assert "service-secret" not in request.full_url
    assert json.loads(request.data) == {"requested_portfolio_date": "2026-08-23"}
    assert request.headers["Apikey"] == "service-secret"
    assert request.headers["Authorization"] == "Bearer service-secret"
    assert timeout == 10.0


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"needs_collection": 1, "lineup_due": False, "quote_due": False, "recoverable_due": False},
        {"needs_collection": False, "lineup_due": False, "quote_due": False},
    ],
)
def test_client_rejects_malformed_status(payload):
    with pytest.raises(RuntimeError, match="invalid response"):
        AdaptiveWorkClient(
            "https://example.supabase.co",
            "secret",
            opener=lambda _request, *, timeout: Response(payload),
        ).status("2026-08-23")


def test_client_rejects_noncanonical_date_before_http():
    calls = []
    with pytest.raises(ValueError, match="ISO date"):
        AdaptiveWorkClient(
            "https://example.supabase.co",
            "secret",
            opener=lambda *_args: calls.append(True),
        ).status("2026-8-23")
    assert calls == []


def test_full_scan_cli_needs_no_network_or_credentials(capsys):
    assert run_cli(
        ["--scan-mode", "full", "--portfolio-date", "2026-08-23"],
        values={},
        client_factory=lambda *_args: (_ for _ in ()).throw(
            AssertionError("full scan cannot query adaptive RPC")
        ),
    ) == 0
    assert capsys.readouterr().out.strip() == "adaptive_work=needed"


@pytest.mark.parametrize(
    ("needed", "code", "line"),
    [
        (True, 0, "adaptive_work=needed"),
        (False, 3, "adaptive_work=idle"),
    ],
)
def test_adaptive_cli_has_bounded_outcomes(needed, code, line, capsys):
    class FakeClient:
        def status(self, _date):
            return type("Status", (), {"needs_collection": needed})()

    result = run_cli(
        ["--scan-mode", "adaptive", "--portfolio-date", "2026-08-23"],
        values={
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "secret",
        },
        client_factory=lambda *_args: FakeClient(),
    )
    assert result == code
    assert capsys.readouterr().out.strip() == line


def test_adaptive_cli_masks_configuration_and_provider_errors(capsys):
    assert run_cli(
        ["--scan-mode", "adaptive", "--portfolio-date", "2026-08-23"],
        values={},
    ) == 2
    assert capsys.readouterr().out.strip() == "adaptive_work=invalid"

    class Broken:
        def status(self, _date):
            raise RuntimeError("provider leaked secret")

    assert run_cli(
        ["--scan-mode", "adaptive", "--portfolio-date", "2026-08-23"],
        values={
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "secret",
        },
        client_factory=lambda *_args: Broken(),
    ) == 2
    captured = capsys.readouterr()
    assert captured.out.strip() == "adaptive_work=invalid"
    assert "provider" not in captured.out + captured.err
