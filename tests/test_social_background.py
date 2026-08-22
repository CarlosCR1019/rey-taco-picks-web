from __future__ import annotations

import base64
from io import BytesIO
import json
import logging
import struct
import zlib

import pytest
from PIL import Image

from backend.social_background import (
    MAX_DECODED_IMAGE_BYTES,
    MAX_ENCODED_IMAGE_CHARS,
    MAX_JSON_RESPONSE_BYTES,
    CloudflareBackgroundProvider,
)


def _image_bytes(
    *, size: tuple[int, int] = (1080, 1080), image_format: str = "PNG"
) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, "orange").save(buffer, format=image_format)
    return buffer.getvalue()


_AUTO_LENGTH = object()


class _Response:
    def __init__(
        self,
        *,
        status_code=200,
        payload=None,
        body: bytes | None = None,
        content_length: object = _AUTO_LENGTH,
    ):
        self.status_code = status_code
        self.body = (
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
            if body is None
            else body
        )
        self.headers = {}
        if content_length is _AUTO_LENGTH:
            self.headers["Content-Length"] = str(len(self.body))
        elif content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.iterated = False
        self.closed = False

    def json(self):
        raise AssertionError("unsafe response.json() must not be called")

    def iter_content(self, chunk_size: int):
        self.iterated = True
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self):
        self.closed = True


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


def _png_with_declared_size(width: int, height: int) -> bytes:
    png = bytearray(_image_bytes(size=(1, 1)))
    ihdr_data_start = 16
    ihdr_data_end = ihdr_data_start + 13
    png[ihdr_data_start : ihdr_data_start + 8] = struct.pack(
        ">II", width, height
    )
    png[ihdr_data_end : ihdr_data_end + 4] = struct.pack(
        ">I", zlib.crc32(b"IHDR" + png[ihdr_data_start:ihdr_data_end])
    )
    return bytes(png)


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
    assert session.response.closed is True
    url, kwargs = session.calls[0]
    assert url == (
        "https://api.cloudflare.com/client/v4/accounts/acct/ai/run/"
        "@cf/black-forest-labs/flux-2-dev"
    )
    assert kwargs["timeout"] == 20
    assert kwargs["stream"] is True
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


def test_missing_content_length_streams_a_bounded_valid_response():
    response = _Response(
        payload=_payload(_image_bytes()), content_length=None
    )
    provider = CloudflareBackgroundProvider(
        account_id="acct", api_token="token", session=_Session(response)
    )

    assert provider.create() is not None
    assert response.iterated is True


def test_oversize_content_length_is_rejected_before_streaming():
    response = _Response(
        payload=_payload(_image_bytes()),
        content_length=MAX_JSON_RESPONSE_BYTES + 1,
    )
    provider = CloudflareBackgroundProvider(
        account_id="acct", api_token="token", session=_Session(response)
    )

    assert provider.create() is None
    assert response.iterated is False
    assert response.closed is True


def test_lying_content_length_cannot_bypass_stream_limit():
    response = _Response(
        body=b"x" * (MAX_JSON_RESPONSE_BYTES + 1), content_length=1
    )
    provider = CloudflareBackgroundProvider(
        account_id="acct", api_token="token", session=_Session(response)
    )

    assert provider.create() is None
    assert response.iterated is True


def test_oversized_encoded_image_is_rejected_before_base64_decode():
    payload = {
        "success": True,
        "result": {"image": "A" * (MAX_ENCODED_IMAGE_CHARS + 1)},
    }
    provider = CloudflareBackgroundProvider(
        account_id="acct",
        api_token="token",
        session=_Session(_Response(payload=payload, content_length=None)),
    )

    assert provider.create() is None


def test_oversized_decoded_image_is_rejected_before_pillow():
    oversized = b"x" * (MAX_DECODED_IMAGE_BYTES + 1)
    provider = CloudflareBackgroundProvider(
        account_id="acct",
        api_token="token",
        session=_Session(
            _Response(payload=_payload(oversized), content_length=None)
        ),
    )

    assert provider.create() is None


@pytest.mark.parametrize(
    "declared_size",
    [(4097, 1), (4096, 4096), (20000, 20000)],
)
def test_excessive_declared_dimensions_fail_before_pixel_allocation(declared_size):
    raw = _png_with_declared_size(*declared_size)
    provider = CloudflareBackgroundProvider(
        account_id="acct",
        api_token="token",
        session=_Session(_Response(payload=_payload(raw))),
    )

    assert provider.create() is None
