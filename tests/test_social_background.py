from __future__ import annotations

import base64
from io import BytesIO
import logging

import pytest
from PIL import Image

from backend.social_background import CloudflareBackgroundProvider


def _image_bytes(
    *, size: tuple[int, int] = (1080, 1080), image_format: str = "PNG"
) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, "orange").save(buffer, format=image_format)
    return buffer.getvalue()


class _Response:
    def __init__(self, *, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def _payload(raw: bytes) -> dict[str, object]:
    return {
        "success": True,
        "result": {"image": base64.b64encode(raw).decode("ascii")},
    }


@pytest.mark.parametrize(
    ("account_id", "api_token"),
    [("", "token"), ("account", ""), (" ", "token"), ("account", " ")],
)
def test_missing_configuration_returns_none_without_request(account_id, api_token):
    session = _Session()
    provider = CloudflareBackgroundProvider(
        account_id=account_id, api_token=api_token, session=session
    )

    assert provider.create() is None
    assert session.calls == []


@pytest.mark.parametrize(
    "response",
    [
        _Response(status_code=429, payload={"private": "body"}),
        _Response(payload={"success": True, "result": {"image": "%%%"}}),
        _Response(payload=_payload(b"not an image")),
        _Response(payload=_payload(_image_bytes(size=(64, 64)))),
    ],
)
def test_invalid_provider_output_returns_none(response):
    provider = CloudflareBackgroundProvider(
        account_id="account", api_token="secret", session=_Session(response)
    )

    assert provider.create() is None


def test_timeout_returns_none_and_logs_only_exception_class(caplog):
    provider = CloudflareBackgroundProvider(
        account_id="account",
        api_token="secret-token",
        session=_Session(error=TimeoutError("secret response body")),
    )

    with caplog.at_level(logging.INFO):
        assert provider.create() is None

    assert "TimeoutError" in caplog.text
    assert "secret response body" not in caplog.text
    assert "secret-token" not in caplog.text


def test_valid_response_uses_constant_generic_prompt_and_normalizes_image():
    session = _Session(_Response(payload=_payload(_image_bytes(size=(1200, 900)))))
    provider = CloudflareBackgroundProvider(
        account_id="acct", api_token="token", session=session
    )

    result = provider.create()

    assert result is not None
    with Image.open(BytesIO(result)) as image:
        assert image.size == (1080, 1080)
        assert image.mode == "RGB"
        assert image.format in {"JPEG", "PNG"}
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == (
        "https://api.cloudflare.com/client/v4/accounts/acct/ai/run/"
        "@cf/black-forest-labs/flux-2-dev"
    )
    assert kwargs["timeout"] == 20
    assert kwargs["headers"] == {"Authorization": "Bearer token"}
    assert "json" not in kwargs
    assert kwargs["files"]["width"] == (None, "1080")
    assert kwargs["files"]["height"] == (None, "1080")
    prompt = kwargs["files"]["prompt"][1].casefold()
    assert "text-free" in prompt
    assert "logo-free" in prompt
    assert "generic sports atmosphere" in prompt
    for forbidden in (
        "américa",
        "tigres",
        "liga mx",
        "ganador del partido",
        "sportsbook",
        "athlete",
    ):
        assert forbidden not in prompt
