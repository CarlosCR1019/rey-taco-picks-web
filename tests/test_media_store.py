from backend.media_storage import build_media_store, media_storage_backend, remotion_enabled
from backend.supabase_media_store import SupabaseMediaStore


def test_storage_backend_defaults_to_supabase(monkeypatch):
    monkeypatch.delenv("MEDIA_STORAGE_BACKEND", raising=False)
    assert media_storage_backend() == "supabase"


def test_unknown_storage_backend_fails_closed(monkeypatch):
    monkeypatch.setenv("MEDIA_STORAGE_BACKEND", "unknown")
    try:
        media_storage_backend()
    except RuntimeError as error:
        assert str(error) == "unsupported media storage backend"
    else:
        raise AssertionError("unsupported backend must fail")


def test_remotion_is_disabled_without_explicit_flag(monkeypatch):
    monkeypatch.delenv("REMOTION_ENABLED", raising=False)
    assert remotion_enabled() is False


def test_media_store_factory_keeps_supabase_as_default():
    class Storage:
        def from_(self, bucket):
            return object()

    class Client:
        storage = Storage()

    value = build_media_store(
        supabase_client=Client(),
        supabase_url="https://dqwuaocyyohwkkuldsmp.supabase.co",
        service_role_key="service-role",
    )
    assert isinstance(value, SupabaseMediaStore)
