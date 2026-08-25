"""Shared bounded and sanitized primitives for Meta Graph HTTP calls."""

from collections.abc import Iterable, Mapping
import json
import re
from typing import Protocol


MAX_META_RESPONSE_BYTES = 256 * 1024
_META_RESPONSE_CHUNK_BYTES = 64 * 1024
_SAFE_META_ID = re.compile(r"^[A-Za-z0-9_:-]{1,200}$")
_GRAPH_VERSION = re.compile(r"^v[0-9]+[.][0-9]+$")
_CONTENT_LENGTH = re.compile(r"^(?:0|[1-9][0-9]*)$")


class MetaSettingsLike(Protocol):
    graph_version: str


class MetaResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def iter_content(self, chunk_size: int) -> Iterable[bytes]: ...

    def close(self) -> None: ...


def read_meta_json(response: MetaResponse) -> tuple[int, object]:
    """Read one JSON object from a streamed Meta response within a fixed cap."""
    try:
        status = response.status_code
        if type(status) is not int:
            raise ValueError("invalid HTTP status")
        headers = response.headers
        if not isinstance(headers, Mapping):
            raise ValueError("invalid response headers")
        declared_text = headers.get("Content-Length")
        declared_length: int | None = None
        if declared_text is not None:
            if (
                not isinstance(declared_text, str)
                or _CONTENT_LENGTH.fullmatch(declared_text) is None
            ):
                raise ValueError("invalid Content-Length")
            declared_length = int(declared_text)
            if declared_length > MAX_META_RESPONSE_BYTES:
                raise ValueError("Meta response body is oversized")
        body = bytearray()
        for chunk in response.iter_content(chunk_size=_META_RESPONSE_CHUNK_BYTES):
            if not isinstance(chunk, bytes):
                raise ValueError("invalid Meta response chunk")
            if not chunk:
                continue
            remaining = MAX_META_RESPONSE_BYTES - len(body)
            if declared_length is not None:
                remaining = min(remaining, declared_length - len(body))
            if len(chunk) > remaining:
                raise ValueError("Meta response body is oversized")
            body.extend(chunk)
        if declared_length is not None and len(body) != declared_length:
            raise ValueError("Meta response Content-Length mismatch")
        payload = json.loads(bytes(body).decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("invalid JSON response")
        return status, payload
    finally:
        response.close()


def safe_meta_id(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("id")
    if not isinstance(value, str) or _SAFE_META_ID.fullmatch(value) is None:
        return None
    return value


def meta_token_invalid(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return False
    return error.get("code") == 190


def meta_auth_headers(token: str) -> dict[str, str]:
    if (
        not isinstance(token, str)
        or not token
        or token != token.strip()
        or any(ord(character) < 32 for character in token)
    ):
        raise ValueError("Meta token is unsafe")
    return {
        "Authorization": f"Bearer {token}",
        "Accept-Encoding": "identity",
    }


def meta_graph_url(settings: MetaSettingsLike, path: str) -> str:
    if (
        not isinstance(settings.graph_version, str)
        or _GRAPH_VERSION.fullmatch(settings.graph_version) is None
    ):
        raise ValueError("Meta graph version is invalid")
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or ".." in path
        or any(ord(character) < 32 for character in path)
    ):
        raise ValueError("Meta graph path is invalid")
    return f"https://graph.facebook.com/{settings.graph_version}/{path}"
