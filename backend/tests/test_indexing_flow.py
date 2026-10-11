import pytest
from sqlalchemy import func, select

from app.main import app
from app.models import DocumentChunk
from app.services.embeddings import get_embeddings
from tests.fakes import FakeEmbeddings

TEXT = "Synthetic quarterly budget review notes."
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def embedder(client):
    fake = FakeEmbeddings()
    app.dependency_overrides[get_embeddings] = lambda: fake
    return fake


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
    ).json()


def reprocess(client, headers, doc_id):
    return client.post(f"/documents/{doc_id}/reprocess", headers=headers)


def test_reprocess_indexes_the_document(client, embedder):
    headers = make_user(client)
    doc = upload(client, headers)
    assert doc["status"] == "uploaded"
    response = reprocess(client, headers, doc["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "indexed"
    assert body["indexed_at"] is not None and body["error_message"] is None


def test_indexed_document_becomes_searchable(client, embedder):
    headers = make_user(client)
    doc = upload(client, headers, "budget.txt")
    reprocess(client, headers, doc["id"])
    response = client.get("/search", headers=headers, params={"q": TEXT})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["filename"] == "budget.txt"
    assert body["results"][0]["excerpt"] == TEXT


def test_unindexed_document_is_not_searchable(client, embedder):
    headers = make_user(client)
    upload(client, headers)
    response = client.get("/search", headers=headers, params={"q": TEXT})
    assert response.json()["count"] == 0


def test_reprocessing_twice_does_not_duplicate_chunks(client, embedder, db_session):
    headers = make_user(client)
    doc = upload(client, headers)
    reprocess(client, headers, doc["id"])
    count = lambda: db_session.scalar(select(func.count()).select_from(DocumentChunk))
    first = count()
    assert first >= 1
    assert reprocess(client, headers, doc["id"]).status_code == 200
    assert count() == first
    assert embedder.calls == 2


def test_other_user_cannot_search_indexed_text(client, embedder):
    alice = make_user(client, "alice@example.com")
    bob = make_user(client, "bob@example.com")
    reprocess(client, alice, upload(client, alice)["id"])
    assert client.get("/search", headers=alice, params={"q": TEXT}).json()["count"] == 1
    bob_search = client.get("/search", headers=bob, params={"q": TEXT})
    assert bob_search.status_code == 200
    assert bob_search.json()["results"] == []


def test_corrupt_file_stays_failed_and_unsearchable(client, embedder):
    headers = make_user(client)
    doc = upload(client, headers, "bad.docx", b"PK\x03\x04garbage", DOCX_MIME)
    assert doc["status"] == "failed"
    body = reprocess(client, headers, doc["id"]).json()
    assert body["status"] == "failed" and body["error_message"]
    assert client.get("/search", headers=headers, params={"q": "garbage"}).json()["count"] == 0


def test_embedding_failure_marks_document_failed(client):
    app.dependency_overrides[get_embeddings] = lambda: FakeEmbeddings(fail=True)
    headers = make_user(client)
    doc = upload(client, headers)
    body = reprocess(client, headers, doc["id"]).json()
    assert body["status"] == "failed"
    assert body["error_message"] == "The embedding step failed"