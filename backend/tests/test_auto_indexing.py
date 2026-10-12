import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.main import app
from app.services.embeddings import get_embeddings
from app.services.encryption import FileEncryptor
from app.services.indexing import get_indexer, ingest_by_id
from app.services.storage import LocalEncryptedStorage
from tests.fakes import FakeEmbeddings

TEXT = "Synthetic quarterly budget review notes."
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def indexing(client, engine, storage_dir):
    """Turn real background indexing on, using a fake embedder and the test database."""
    embedder = FakeEmbeddings()
    calls = []
    storage = LocalEncryptedStorage(storage_dir, FileEncryptor(settings.encryption_key_bytes))
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def indexer(document_id):
        calls.append(document_id)
        ingest_by_id(
            document_id,
            session_factory=session_factory,
            storage=storage,
            embeddings=embedder,
        )

    app.dependency_overrides[get_indexer] = lambda: indexer
    app.dependency_overrides[get_embeddings] = lambda: embedder  # used by /search
    return SimpleNamespace(embedder=embedder, calls=calls, session_factory=session_factory, storage=storage)


def make_user(client, email="alice@example.com"):
    client.post(
        "/auth/register",
        json={"email": email, "full_name": "Test Person", "password": "Correct-Horse-9"},
    )
    token = client.post(
        "/auth/login", data={"username": email, "password": "Correct-Horse-9"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def upload(client, headers, name="notes.txt", data=TEXT.encode(), ctype="text/plain"):
    return client.post(
        "/documents/upload", headers=headers, files={"file": (name, data, ctype)}
    )


def test_upload_indexes_the_document_automatically(client, indexing):
    headers = make_user(client)
    response = upload(client, headers)
    assert response.status_code == 201
    doc_id = response.json()["id"]
    detail = client.get(f"/documents/{doc_id}", headers=headers).json()
    assert detail["status"] == "indexed" and detail["indexed_at"] is not None


def test_auto_indexed_document_is_searchable(client, indexing):
    headers = make_user(client)
    upload(client, headers, "budget.txt")
    body = client.get("/search", headers=headers, params={"q": TEXT}).json()
    assert body["count"] == 1 and body["results"][0]["filename"] == "budget.txt"


def test_corrupt_upload_is_not_queued_for_indexing(client, indexing):
    headers = make_user(client)
    response = upload(client, headers, "bad.docx", b"PK\x03\x04garbage", DOCX_MIME)
    assert response.status_code == 201 and response.json()["status"] == "failed"
    assert indexing.calls == []


def test_duplicate_upload_is_indexed_only_once(client, indexing):
    headers = make_user(client)
    assert upload(client, headers).status_code == 201
    assert upload(client, headers).status_code == 409
    assert len(indexing.calls) == 1


def test_indexing_failure_does_not_fail_the_upload(client, indexing):
    indexing.embedder.fail = True
    headers = make_user(client)
    response = upload(client, headers)
    assert response.status_code == 201
    detail = client.get(f"/documents/{response.json()['id']}", headers=headers).json()
    assert detail["status"] == "failed"
    assert detail["error_message"] == "The embedding step failed"


def test_other_user_cannot_search_auto_indexed_text(client, indexing):
    alice = make_user(client, "alice@example.com")
    bob = make_user(client, "bob@example.com")
    upload(client, alice)
    assert client.get("/search", headers=alice, params={"q": TEXT}).json()["count"] == 1
    assert client.get("/search", headers=bob, params={"q": TEXT}).json()["results"] == []


def test_indexing_a_deleted_document_is_harmless(indexing):
    ingest_by_id(
        uuid.uuid4(),
        session_factory=indexing.session_factory,
        storage=indexing.storage,
        embeddings=indexing.embedder,
    )