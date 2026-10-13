import uuid

import pytest

from app.services import indexing
from app.services.encryption import DecryptionError, FileEncryptor
from app.services.ingestion import IngestionBusy

KEY = bytes(range(32))
AAD = b"document-id-1"


# ---------- encryption failure paths ----------

def test_key_must_be_32_bytes():
    with pytest.raises(ValueError):
        FileEncryptor(b"short")


def test_round_trip():
    enc = FileEncryptor(KEY)
    assert enc.decrypt(enc.encrypt(b"secret", AAD), AAD) == b"secret"


def test_same_plaintext_encrypts_differently_each_time():
    enc = FileEncryptor(KEY)
    assert enc.encrypt(b"secret", AAD) != enc.encrypt(b"secret", AAD)


def test_truncated_blob_is_rejected():
    enc = FileEncryptor(KEY)
    with pytest.raises(DecryptionError):
        enc.decrypt(b"too short", AAD)


def test_tampered_ciphertext_is_rejected():
    enc = FileEncryptor(KEY)
    blob = bytearray(enc.encrypt(b"secret data", AAD))
    blob[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        enc.decrypt(bytes(blob), AAD)


def test_wrong_key_is_rejected():
    blob = FileEncryptor(KEY).encrypt(b"secret", AAD)
    with pytest.raises(DecryptionError):
        FileEncryptor(bytes(reversed(KEY))).decrypt(blob, AAD)


def test_wrong_associated_data_is_rejected():
    # A file blob moved to another document's record must not decrypt.
    enc = FileEncryptor(KEY)
    blob = enc.encrypt(b"secret", b"document-A")
    with pytest.raises(DecryptionError):
        enc.decrypt(blob, b"document-B")


# ---------- background indexing safety net ----------

class FakeSession:
    def __init__(self, document):
        self.document = document
        self.closed = False

    def get(self, model, key):
        return self.document

    def close(self):
        self.closed = True


def run_job(session):
    indexing.ingest_by_id(
        uuid.uuid4(),
        session_factory=lambda: session,
        storage=object(),
        embeddings=object(),
    )


def test_indexing_failure_is_contained_and_session_closed(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(indexing, "ingest_document", boom)
    session = FakeSession(document=object())
    run_job(session)  # must not raise
    assert session.closed


def test_indexing_busy_document_is_skipped(monkeypatch):
    def busy(*args, **kwargs):
        raise IngestionBusy()

    monkeypatch.setattr(indexing, "ingest_document", busy)
    session = FakeSession(document=object())
    run_job(session)  # must not raise
    assert session.closed


def test_indexing_missing_document_is_ignored(monkeypatch):
    called = []
    monkeypatch.setattr(indexing, "ingest_document", lambda *a, **k: called.append(1))
    session = FakeSession(document=None)
    run_job(session)
    assert called == [] and session.closed


def test_get_indexer_runs_ingest_with_real_dependencies(monkeypatch):
    calls = {}

    def fake_ingest_by_id(document_id, **kwargs):
        calls["id"] = document_id
        calls["keys"] = set(kwargs)

    monkeypatch.setattr(indexing, "ingest_by_id", fake_ingest_by_id)
    monkeypatch.setattr(indexing, "get_storage", lambda: "storage")
    monkeypatch.setattr(indexing, "get_embeddings", lambda: "embeddings")

    doc_id = uuid.uuid4()
    indexing.get_indexer()(doc_id)
    assert calls["id"] == doc_id
    assert calls["keys"] == {"session_factory", "storage", "embeddings"}