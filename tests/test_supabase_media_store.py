import hashlib

from backend.supabase_media_store import SupabaseMediaStore


class StorageResponse:
    path = "derived/2026-09-05/daily_results_reel/"
    full_path = "social-vertical/derived/2026-09-05/daily_results_reel/"
    fullPath = full_path


class FakeBucket:
    def upload(self, *, path, file, file_options):
        response = StorageResponse()
        response.path = path
        response.full_path = f"social-vertical/{path}"
        response.fullPath = response.full_path
        self.uploaded = (path, file, file_options)
        return response

    def download(self, path):
        return b"downloaded"

    def create_signed_url(self, path, expires_in):
        return {"signedURL": f"https://dqwuaocyyohwkkuldsmp.supabase.co/storage/v1/object/sign/social-vertical/{path}?token=test"}

    def remove(self, paths):
        return [{"name": paths[0]}]

    def get_public_url(self, path):
        return f"https://dqwuaocyyohwkkuldsmp.supabase.co/storage/v1/object/public/social-vertical/{path}"


class FakeStorage:
    def __init__(self):
        self.bucket = FakeBucket()

    def from_(self, bucket):
        assert bucket == "social-vertical"
        return self.bucket


class FakeClient:
    def __init__(self):
        self.storage = FakeStorage()


def test_supabase_adapter_uses_existing_bucket_and_contract():
    payload = b"bytes"
    digest = hashlib.sha256(payload).hexdigest()
    store = SupabaseMediaStore(
        client=FakeClient(),
        supabase_url="https://dqwuaocyyohwkkuldsmp.supabase.co",
        service_role_key="service-role",
    )
    result = store.put(
        "derived/2026-09-05/daily_results_reel/" + digest + ".mp4",
        payload,
        "video/mp4",
        {},
    )
    assert result.digest == digest
    assert result.public is True
    assert store.get("derived/2026-09-05/daily_results_reel/" + digest + ".mp4") == b"downloaded"


def test_supabase_adapter_never_deletes_approved_object():
    store = SupabaseMediaStore(
        client=FakeClient(),
        supabase_url="https://dqwuaocyyohwkkuldsmp.supabase.co",
        service_role_key="service-role",
    )
    try:
        store.delete_temporary("derived/2026-09-05/daily_results_reel/" + "a" * 64 + ".mp4")
    except ValueError as error:
        assert str(error) == "temporary object key is invalid"
    else:
        raise AssertionError("approved objects must not be deleted")
