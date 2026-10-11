import hashlib
import math
from datetime import timedelta

import pymupdf
import pytest
from langchain_core.embeddings import Embeddings
from sqlalchemy import func, select, update

from app.core.config import settings
from app.models import Document, DocumentChunk, DocumentStatus, PIIFinding, User
from app.services import ingestion
from app.services.embeddings import EmbeddingError
from app.services.encryption import FileEncryptor
from app.services.ingestion import IngestionBusy, ingest_document
from app.services.storage import LocalEncryptedStorage, new_storage_id

EMAIL = "priya.sharma@example.com"
SAMPLE = ("Quarterly budget review notes. " * 120) + f"\nContact: {EMAIL}\n"


class FakeEmbeddings(Embeddings):
    """Deterministic 384-dimensional vectors, with no model download."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        raw = [(digest[i % 32] + i) % 17 - 8 for i in range(384)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]

    def embed_documents(self, texts):
        self.calls += 1
        if self.fail:
            raise EmbeddingError("simulated failure")
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)


@pytest.fixture
def storage(storage_dir):
    return LocalEncryptedStorage(storage_dir, FileEncryptor(settings.encryption_key_bytes))


def make_user(db, email="alice@example.com"):
    user = User(email=email, full_name="Test Person", hashed_password="not-a-real-hash")
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def owner(db_session):
    return make_user(db_session)


def make_document(db, storage, owner, name="notes.txt", data=SAMPLE.encode()):
    storage_id = new_storage_id()
    storage.save(storage_id, data)
    document = Document(
        owner_id=owner.id,
        original_filename=name,
        storage_id=storage_id,
        mime_type="text/plain",
        size_bytes=len(data),
        file_hash=hashlib.sha256(data).hexdigest(),
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def count(db, model, document):
    return db.scalar(
        select(func.count()).select_from(model).where(model.document_id == document.id)
    )


def test_ingest_indexes_document_and_stores_chunks(db_session, storage, owner):
    document = make_document(db_session, storage, owner)
    result = ingest_document(db_session, storage, FakeEmbeddings(), document)
    assert result.status == DocumentStatus.INDEXED
    assert result.indexed_at is not None and result.error_message is None

    chunks = db_session.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
    ).all()
    assert len(chunks) > 1
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.owner_id == owner.id for c in chunks)
    assert all(len(c.embedding) == 384 for c in chunks)


def test_ingest_stores_pii_findings(db_session, storage, owner):
    document = make_document(db_session, storage, owner)
    ingest_document(db_session, storage, FakeEmbeddings(), document)
    categories = set(
        db_session.scalars(
            select(PIIFinding.category).where(PIIFinding.document_id == document.id)
        )
    )
    assert "EMAIL_ADDRESS" in categories


def test_second_run_does_not_embed_again(db_session, storage, owner):
    document = make_document(db_session, storage, owner)
    embedder = FakeEmbeddings()
    ingest_document(db_session, storage, embedder, document)
    first_count = count(db_session, DocumentChunk, document)
    ingest_document(db_session, storage, embedder, document)
    assert embedder.calls == 1
    assert count(db_session, DocumentChunk, document) == first_count


def test_forced_reprocess_replaces_without_duplicates(db_session, storage, owner):
    document = make_document(db_session, storage, owner)
    embedder = FakeEmbeddings()
    ingest_document(db_session, storage, embedder, document)
    chunks_before = count(db_session, DocumentChunk, document)
    findings_before = count(db_session, PIIFinding, document)
    ingest_document(db_session, storage, embedder, document, force=True)
    assert embedder.calls == 2
    assert count(db_session, DocumentChunk, document) == chunks_before
    assert count(db_session, PIIFinding, document) == findings_before


def test_pdf_chunks_keep_page_numbers(db_session, storage, owner):
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Quarterly summary on page one")
    pdf.new_page().insert_text((72, 72), "Budget details on page two")
    document = make_document(db_session, storage, owner, "report.pdf", pdf.tobytes())
    result = ingest_document(db_session, storage, FakeEmbeddings(), document)
    pages = set(
        db_session.scalars(
            select(DocumentChunk.page_number).where(DocumentChunk.document_id == document.id)
        )
    )
    assert pages == {1, 2} and result.page_count == 2


def test_corrupt_file_is_marked_failed_with_nothing_stored(db_session, storage, owner):
    document = make_document(db_session, storage, owner, "bad.docx", b"PK\x03\x04garbage")
    result = ingest_document(db_session, storage, FakeEmbeddings(), document)
    assert result.status == DocumentStatus.FAILED
    assert result.error_message and result.indexed_at is None
    assert count(db_session, DocumentChunk, document) == 0


def test_embedding_failure_marks_failed_and_stores_nothing(db_session, storage, owner):
    document = make_document(db_session, storage, owner)
    result = ingest_document(db_session, storage, FakeEmbeddings(fail=True), document)
    assert result.status == DocumentStatus.FAILED
    assert result.error_message == "The embedding step failed"
    assert count(db_session, DocumentChunk, document) == 0
    assert count(db_session, PIIFinding, document) == 0


def test_failed_reindex_keeps_old_index_but_marks_failed(db_session, storage, owner):
    document = make_document(db_session, storage, owner)
    ingest_document(db_session, storage, FakeEmbeddings(), document)
    chunks_before = count(db_session, DocumentChunk, document)
    result = ingest_document(
        db_session, storage, FakeEmbeddings(fail=True), document, force=True
    )
    assert result.status == DocumentStatus.FAILED
    assert count(db_session, DocumentChunk, document) == chunks_before


def test_document_being_processed_is_rejected(db_session, storage, owner):
    document = make_document(db_session, storage, owner)
    db_session.execute(
        update(Document)
        .where(Document.id == document.id)
        .values(status=DocumentStatus.PROCESSING)
    )
    db_session.commit()
    with pytest.raises(IngestionBusy):
        ingest_document(db_session, storage, FakeEmbeddings(), document)


def test_stale_processing_document_can_be_reclaimed(db_session, storage, owner):
    document = make_document(db_session, storage, owner)
    db_session.execute(
        update(Document)
        .where(Document.id == document.id)
        .values(
            status=DocumentStatus.PROCESSING,
            updated_at=func.now() - timedelta(hours=1),
        )
    )
    db_session.commit()
    result = ingest_document(db_session, storage, FakeEmbeddings(), document)
    assert result.status == DocumentStatus.INDEXED


def test_chunk_limit_is_enforced(db_session, storage, owner, monkeypatch):
    monkeypatch.setattr(ingestion, "MAX_CHUNKS_PER_DOCUMENT", 2)
    document = make_document(db_session, storage, owner)
    result = ingest_document(db_session, storage, FakeEmbeddings(), document)
    assert result.status == DocumentStatus.FAILED
    assert "too large" in result.error_message
    assert count(db_session, DocumentChunk, document) == 0


def test_each_users_chunks_stay_with_their_owner(db_session, storage, owner):
    bob = make_user(db_session, "bob@example.com")
    alice_doc = make_document(db_session, storage, owner, data=SAMPLE.encode())
    bob_doc = make_document(db_session, storage, bob, data=b"Bob private notes about hiking trips")
    ingest_document(db_session, storage, FakeEmbeddings(), alice_doc)
    ingest_document(db_session, storage, FakeEmbeddings(), bob_doc)
    bob_chunks = db_session.scalars(
        select(DocumentChunk).where(DocumentChunk.owner_id == bob.id)
    ).all()
    assert len(bob_chunks) == 1 and bob_chunks[0].document_id == bob_doc.id
    assert all(c.document_id != alice_doc.id for c in bob_chunks)


def test_deleting_a_document_removes_its_chunks(db_session, storage, owner):
    document = make_document(db_session, storage, owner)
    ingest_document(db_session, storage, FakeEmbeddings(), document)
    assert count(db_session, DocumentChunk, document) > 0
    db_session.delete(document)
    db_session.commit()
    db_session.expire_all()
    assert (
        db_session.scalar(select(func.count()).select_from(DocumentChunk)) == 0
    )