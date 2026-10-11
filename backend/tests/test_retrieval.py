import uuid

import pytest
from langchain_core.documents import Document as LCDocument

from app.core.config import settings
from app.models import Document, DocumentChunk, DocumentStatus, User
from app.services.embeddings import LocalEmbeddings
from app.services.retrieval import UserScopedRetriever, search_chunks
from app.services.storage import new_storage_id
from tests.fakes import FakeEmbeddings


@pytest.fixture
def embedder():
    return FakeEmbeddings()


def make_user(db, email="alice@example.com"):
    user = User(email=email, full_name="Test Person", hashed_password="not-a-real-hash")
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def owner(db_session):
    return make_user(db_session)


def make_document(db, owner, name="notes.txt", status=DocumentStatus.INDEXED):
    document = Document(
        owner_id=owner.id,
        original_filename=name,
        storage_id=new_storage_id(),
        mime_type="text/plain",
        size_bytes=10,
        file_hash=uuid.uuid4().hex,
        status=status,
    )
    db.add(document)
    db.commit()
    return document


def add_chunk(db, document, index, text, embedder, page=None):
    chunk = DocumentChunk(
        document_id=document.id,
        owner_id=document.owner_id,
        chunk_index=index,
        page_number=page,
        content=text,
        embedding=embedder.embed_query(text),
    )
    db.add(chunk)
    db.commit()
    return chunk


def test_most_similar_chunk_ranks_first(db_session, owner, embedder):
    document = make_document(db_session, owner)
    texts = [
        "Rent is due on the first of every month.",
        "The team offsite is planned for June.",
        "Insurance renewal is in October.",
    ]
    for index, text in enumerate(texts):
        add_chunk(db_session, document, index, text, embedder)
    hits = search_chunks(db_session, owner.id, embedder, texts[1], top_k=3)
    assert len(hits) == 3
    assert hits[0].content == texts[1] and hits[0].distance < 0.001


def test_never_returns_another_users_chunks(db_session, owner, embedder):
    bob = make_user(db_session, "bob@example.com")
    secret = "Bob confidential salary negotiation notes."
    add_chunk(db_session, make_document(db_session, bob), 0, secret, embedder)
    add_chunk(db_session, make_document(db_session, owner), 0, "Alice grocery list.", embedder)

    # Alice searches with Bob's exact text: a perfect match that she must not see.
    alice_hits = search_chunks(db_session, owner.id, embedder, secret, top_k=10)
    assert [h.content for h in alice_hits] == ["Alice grocery list."]

    bob_hits = search_chunks(db_session, bob.id, embedder, secret, top_k=10)
    assert [h.content for h in bob_hits] == [secret]


def test_document_filter_cannot_reach_foreign_documents(db_session, owner, embedder):
    bob = make_user(db_session, "bob@example.com")
    bob_doc = make_document(db_session, bob)
    add_chunk(db_session, bob_doc, 0, "Bob private text.", embedder)
    hits = search_chunks(
        db_session, owner.id, embedder, "Bob private text.", document_ids=[bob_doc.id]
    )
    assert hits == []


@pytest.mark.parametrize(
    "status",
    [DocumentStatus.FAILED, DocumentStatus.PROCESSING, DocumentStatus.UPLOADED],
)
def test_only_indexed_documents_are_searched(db_session, owner, embedder, status):
    document = make_document(db_session, owner, status=status)
    add_chunk(db_session, document, 0, "Some stored text.", embedder)
    assert search_chunks(db_session, owner.id, embedder, "Some stored text.") == []


def test_top_k_limits_results(db_session, owner, embedder):
    document = make_document(db_session, owner)
    for index in range(5):
        add_chunk(db_session, document, index, f"Distinct chunk number {index}.", embedder)
    assert len(search_chunks(db_session, owner.id, embedder, "anything", top_k=3)) == 3


def test_max_distance_removes_unrelated_results(db_session, owner, embedder):
    document = make_document(db_session, owner)
    add_chunk(db_session, document, 0, "Quarterly budget summary.", embedder)
    exact = search_chunks(
        db_session, owner.id, embedder, "Quarterly budget summary.", max_distance=0.3
    )
    unrelated = search_chunks(
        db_session, owner.id, embedder, "Completely different question.", max_distance=0.3
    )
    assert len(exact) == 1 and unrelated == []


def test_retriever_returns_langchain_documents_with_safe_metadata(db_session, owner, embedder):
    document = make_document(db_session, owner, name="plan.txt")
    add_chunk(db_session, document, 0, "Project plan milestone one.", embedder, page=3)
    retriever = UserScopedRetriever(
        db=db_session, owner_id=owner.id, embeddings=embedder, top_k=2
    )
    results = retriever.invoke("Project plan milestone one.")
    assert len(results) == 1 and isinstance(results[0], LCDocument)
    assert results[0].page_content == "Project plan milestone one."
    meta = results[0].metadata
    assert meta["filename"] == "plan.txt" and meta["page_number"] == 3
    assert meta["document_id"] == str(document.id)
    assert "owner_id" not in meta and "storage_id" not in meta


def test_empty_query_returns_nothing_without_embedding(db_session, owner, embedder):
    assert search_chunks(db_session, owner.id, embedder, "   ") == []
    assert embedder.query_calls == 0


def test_deleted_document_disappears_from_search(db_session, owner, embedder):
    document = make_document(db_session, owner)
    add_chunk(db_session, document, 0, "Text that will be deleted.", embedder)
    db_session.delete(document)
    db_session.commit()
    assert search_chunks(db_session, owner.id, embedder, "Text that will be deleted.") == []


def test_real_model_ranks_related_text_first(db_session, owner):
    embedder = LocalEmbeddings(settings.embedding_model, settings.embedding_dimension)
    document = make_document(db_session, owner)
    texts = [
        "The electricity bill for March was 4,200 rupees and was paid on the 5th.",
        "The best hiking trail in autumn is the ridge route with views of the valley.",
        "Mix the flour and eggs, then rest the pasta dough for thirty minutes.",
    ]
    for index, text in enumerate(texts):
        add_chunk(db_session, document, index, text, embedder)

    bill = search_chunks(db_session, owner.id, embedder, "How much was the electricity bill?", top_k=1)
    trail = search_chunks(db_session, owner.id, embedder, "Which trail should I hike in autumn?", top_k=1)
    assert bill[0].content == texts[0]
    assert trail[0].content == texts[1]