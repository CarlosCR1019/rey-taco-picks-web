from __future__ import annotations


class PlaydoitSourceError(RuntimeError):
    code = "source_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class PlaydoitSourceBlocked(PlaydoitSourceError):
    code = "source_blocked"


class PlaydoitSourceInvalid(PlaydoitSourceError):
    code = "source_invalid"


def assert_playdoit_source_healthy(*, title: str, body: str, source: str) -> None:
    normalized_title = title.casefold()
    normalized_body = body.casefold()
    normalized_source = source.casefold()
    blocked = "acceso bloqueado" in normalized_title or (
        "ray id" in normalized_body and "tu ip" in normalized_body
    )
    if blocked:
        raise PlaydoitSourceBlocked()
    if "altenar" not in normalized_source:
        raise PlaydoitSourceInvalid()
