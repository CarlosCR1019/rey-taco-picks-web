from backend.media_object_repository import MediaObjectRepository
from backend.media_store import MediaObject


class Response:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, row):
        self.row = row
        self.payload = None

    def upsert(self, payload, *, on_conflict):
        assert on_conflict == "object_key"
        self.payload = payload
        return self

    def execute(self):
        return Response([self.row])


class Client:
    def __init__(self, row):
        self.query = Query(row)

    def table(self, name):
        assert name == "media_objects"
        return self.query


def media_object(digest="a" * 64):
    return MediaObject(
        object_key=f"derived/2026-09-05/daily_results_reel/{digest}.mp4",
        content_type="video/mp4",
        digest=digest,
        size_bytes=100,
        public=True,
    )


def test_register_approved_is_idempotent_and_returns_key():
    value = media_object()
    client = Client({"object_key": value.object_key, "digest": value.digest, "content_type": value.content_type})
    repository = MediaObjectRepository(client)
    assert repository.register_approved(
        value,
        portfolio_date="2026-09-05",
        content_kind="daily_results_reel",
        source_batch_id=None,
        storage_backend="r2",
    ) == value.object_key
    assert client.query.payload["state"] == "approved"


def test_register_approved_rejects_identity_conflict():
    value = media_object()
    client = Client({"object_key": value.object_key, "digest": "b" * 64, "content_type": value.content_type})
    repository = MediaObjectRepository(client)
    try:
        repository.register_approved(
            value,
            portfolio_date="2026-09-05",
            content_kind="daily_results_reel",
            source_batch_id=None,
            storage_backend="r2",
        )
    except RuntimeError as error:
        assert str(error) == "media object identity conflict"
    else:
        raise AssertionError("conflicting object identity must fail")
