import uuid

import pytest

from app.models import Document, DocumentChunk, DocumentStatus
from app.services.embeddings import EmbeddingError, get_embeddings
from app.services.storage import new_storage_id
from app.main import app
from tests.fakes import FakeEmbeddings


class BrokenQueryEmbeddings(FakeEmbeddings):
    def embed_query(self, text):
        raise EmbeddingError("simulated failure")


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
    headers = {"Authorization": f"Bearer {token}"}
    user_id = uuid.UUID(client.get("/auth/me", headers=headers).json()["id"])
    return headers, user_id


def seed(db, embedder, owner_id, texts, name="notes.txt", page=None):
    document = Document(
        owner_id=owner_id,
        original_filename=name,
        storage_id=new_storage_id(),
        mime_type="text/plain",
        size_bytes=10,
        file_hash=uuid.uuid4().hex,
        status=DocumentStatus.INDEXED,
    )
    db.add(document)
    db.commit()
    for index, text in enumerate(texts):
        db.add(
            DocumentChunk(
                document_id=document.id,
                owner_id=owner_id,
                chunk_index=index,
                page_number=page,
                content=text,
                embedding=embedder.embed_query(text),
            )
        )
    db.commit()
    return document


def test_search_requires_login(client):
    assert client.get("/search", params={"q": "budget"}).status_code == 401


def test_search_returns_own_hits_without_internal_fields(client, db_session, embedder):
    headers, user_id = make_user(client)
    document = seed(db_session, embedder, user_id, ["Quarterly budget summary."], "plan.txt", page=2)
    response = client.get("/search", headers=headers, params={"q": "Quarterly budget summary."})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    hit = body["results"][0]
    assert hit["filename"] == "plan.txt" and hit["page_number"] == 2
    assert hit["document_id"] == str(document.id)
    assert hit["excerpt"] == "Quarterly budget summary."
    assert "owner_id" not in hit and "storage_id" not in hit


def test_search_never_returns_another_users_text(client, db_session, embedder):
    alice, _ = make_user(client, "alice@example.com")
    _, bob_id = make_user(client, "bob@example.com")
    secret = "Bob confidential salary negotiation notes."
    seed(db_session, embedder, bob_id, [secret])
    response = client.get("/search", headers=alice, params={"q": secret})
    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert response.json()["results"] == []


def test_unrelated_results_are_filtered_by_distance(client, db_session, embedder):
    headers, user_id = make_user(client)
    seed(db_session, embedder, user_id, ["Quarterly budget summary."])
    response = client.get("/search", headers=headers, params={"q": "Completely different question"})
    assert response.status_code == 200 and response.json()["count"] == 0


def test_foreign_document_filter_is_404(client, db_session, embedder):
    alice, _ = make_user(client, "alice@example.com")
    _, bob_id = make_user(client, "bob@example.com")
    bob_doc = seed(db_session, embedder, bob_id, ["Bob private text."])
    response = client.get(
        "/search", headers=alice, params={"q": "Bob private text.", "document_id": str(bob_doc.id)}
    )
    assert response.status_code == 404


def test_own_document_filter_limits_results(client, db_session, embedder):
    headers, user_id = make_user(client)
    first = seed(db_session, embedder, user_id, ["Shared wording here."], "a.txt")
    seed(db_session, embedder, user_id, ["Shared wording here."], "b.txt")
    response = client.get(
        "/search", headers=headers, params={"q": "Shared wording here.", "document_id": str(first.id)}
    )
    results = response.json()["results"]
    assert len(results) == 1 and results[0]["filename"] == "a.txt"


def test_top_k_limits_results(client, db_session, embedder):
    headers, user_id = make_user(client)
    seed(db_session, embedder, user_id, ["Same repeated text."] * 4)
    response = client.get("/search", headers=headers, params={"q": "Same repeated text.", "top_k": 2})
    assert response.json()["count"] == 2


def test_query_validation(client, embedder):
    headers, _ = make_user(client)
    assert client.get("/search", headers=headers).status_code == 422
    assert client.get("/search", headers=headers, params={"q": ""}).status_code == 422
    assert client.get("/search", headers=headers, params={"q": "x" * 501}).status_code == 422
    assert client.get("/search", headers=headers, params={"q": "ok", "top_k": 0}).status_code == 422


def test_embedding_failure_gives_503(client):
    app.dependency_overrides[get_embeddings] = lambda: BrokenQueryEmbeddings()
    headers, _ = make_user(client)
    response = client.get("/search", headers=headers, params={"q": "anything"})
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]