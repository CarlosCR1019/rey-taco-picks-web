import hashlib

import pytest

from backend.r2_media_store import (
    R2MediaStore,
    derived_object_key,
    evidence_object_key,
)


class FakeR2Client:
    def __init__(self):
        self.objects = {}
        self.deleted = []

    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {"ETag": '"test"'}

    def head_object(self, **kwargs):
        if kwargs["Key"] not in self.objects:
            error = RuntimeError("missing")
            error.response = {"Error": {"Code": "404"}}
            raise error
        return {"ContentLength": len(self.objects[kwargs["Key"]])}

    def get_object(self, **kwargs):
        return {"Body": type("Body", (), {"read": lambda self: b"bytes"})()}

    def generate_presigned_url(self, **kwargs):
        return "https://r2.invalid/temporary"

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs["Key"])
        self.objects.pop(kwargs["Key"], None)
        return {}


@pytest.fixture
def fake_r2():
    return FakeR2Client()


def test_object_keys_are_content_addressed():
    assert derived_object_key("2026-09-05", "daily_results_reel", "a" * 64, "mp4") == (
        "derived/2026-09-05/daily_results_reel/" + "a" * 64 + ".mp4"
    )
    assert evidence_object_key("2026-09-05", "b" * 64, "jpg") == (
        "evidence/2026-09-05/" + "b" * 64 + ".jpg"
    )


def test_r2_requires_complete_configuration(monkeypatch):
    for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="R2 configuration is incomplete"):
        R2MediaStore.from_environment(client_factory=lambda **_: object())


def test_delete_temporary_rejects_approved_derived_objects(fake_r2):
    store = R2MediaStore("account", "key", "secret", "bucket", client=fake_r2)
    with pytest.raises(ValueError, match="temporary object key is invalid"):
        store.delete_temporary("derived/2026-09-05/daily_results_reel/" + "c" * 64 + ".mp4")


def test_put_requires_digest_in_content_addressed_key(fake_r2):
    store = R2MediaStore("account", "key", "secret", "bucket", client=fake_r2)
    with pytest.raises(ValueError, match="object digest does not match key"):
        store.put("derived/2026-09-05/daily_results_reel/" + "d" * 64 + ".mp4", b"bytes", "video/mp4", {})


def test_put_returns_digest_without_logging_payload(fake_r2, caplog):
    payload = b"bytes"
    digest = hashlib.sha256(payload).hexdigest()
    store = R2MediaStore("account", "key", "secret", "bucket", client=fake_r2)
    result = store.put(
        "derived/2026-09-05/daily_results_reel/" + digest + ".mp4",
        payload,
        "video/mp4",
        {},
    )
    assert result.digest == digest
    assert result.public is True
    assert "bytes" not in caplog.text
    assert "secret" not in caplog.text
