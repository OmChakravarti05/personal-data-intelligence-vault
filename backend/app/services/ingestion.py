import logging
from datetime import datetime, timedelta, timezone

from langchain_core.embeddings import Embeddings
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk, DocumentStatus, PIIFinding
from app.services.chunking import ChunkData, chunk_segments, document_segments
from app.services.document_parser import ExtractedDocument, ParseError, parse_document
from app.services.embeddings import EmbeddingError
from app.services.encryption import DecryptionError
from app.services.pii_detection import PIIMatch, detect_pii
from app.services.storage import StorageBackend, StorageError

logger = logging.getLogger(__name__)

MAX_CHUNKS_PER_DOCUMENT = 3000
# A document stuck in "processing" longer than this (for example after a crash)
# may be claimed again.
PROCESSING_TIMEOUT = timedelta(minutes=15)


class IngestionBusy(Exception):
    """Another worker is already processing this document."""


class IngestionError(Exception):
    """A processing limit was exceeded. The message is safe to show to the user."""


def _user_message(exc: Exception) -> str:
    """Safe text for Document.error_message. Never includes content or internal paths."""
    if isinstance(exc, (ParseError, IngestionError)):
        return str(exc)
    if isinstance(exc, StorageError):
        return "The stored file could not be found"
    if isinstance(exc, DecryptionError):
        return "The stored file failed its integrity check"
    return "The embedding step failed"


def _chunk_count(db: Session, document: Document) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.document_id == document.id,
                DocumentChunk.owner_id == document.owner_id,
            )
        )
        or 0
    )


def _claim(db: Session, document: Document) -> bool:
    """Atomically move the document to "processing". False if someone else holds it."""
    stale_before = func.now() - PROCESSING_TIMEOUT
    result = db.execute(
        update(Document)
        .where(
            Document.id == document.id,
            Document.owner_id == document.owner_id,
            or_(
                Document.status != DocumentStatus.PROCESSING,
                Document.updated_at < stale_before,
            ),
        )
        .values(status=DocumentStatus.PROCESSING, error_message=None)
    )
    db.commit()
    return result.rowcount == 1


def _store(
    db: Session,
    document: Document,
    parsed: ExtractedDocument,
    pii_by_segment: list[tuple[int | None, list[PIIMatch]]],
    chunks: list[ChunkData],
    vectors: list[list[float]],
) -> None:
    """Replace all stored results and mark indexed, in ONE transaction."""
    try:
        for model in (DocumentChunk, PIIFinding):
            db.execute(
                delete(model).where(
                    model.document_id == document.id,
                    model.owner_id == document.owner_id,
                )
            )
        db.add_all(
            DocumentChunk(
                document_id=document.id,
                owner_id=document.owner_id,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                content=chunk.content,
                embedding=vector,
            )
            for chunk, vector in zip(chunks, vectors)
        )
        db.add_all(
            PIIFinding(
                document_id=document.id,
                owner_id=document.owner_id,
                category=match.category,
                start_char=match.start,
                end_char=match.end,
                page_number=page_number,
                confidence=match.score,
            )
            for page_number, matches in pii_by_segment
            for match in matches
        )
        document.status = DocumentStatus.INDEXED
        document.error_message = None
        document.page_count = parsed.page_count
        document.indexed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()
        raise


def _mark_failed(db: Session, document: Document, message: str) -> None:
    db.rollback()
    document.status = DocumentStatus.FAILED
    document.error_message = message
    db.commit()


def ingest_document(
    db: Session,
    storage: StorageBackend,
    embeddings: Embeddings,
    document: Document,
    *,
    force: bool = False,
) -> Document:
    """Extract, scan, chunk, embed and store a document.

    The document is marked "indexed" only after every step has succeeded and
    everything has been saved. Any failure leaves it "failed" with a safe message.
    """
    # Idempotent: an already-indexed document is not embedded again unless forced.
    if (
        not force
        and document.status == DocumentStatus.INDEXED
        and _chunk_count(db, document) > 0
    ):
        return document

    if not _claim(db, document):
        raise IngestionBusy("Document is already being processed")
    db.refresh(document)

    try:
        data = storage.read(document.storage_id)
        extension = "." + document.original_filename.rsplit(".", 1)[-1]
        parsed = parse_document(data, extension)
        segments = document_segments(parsed)

        pii_by_segment = [(page, detect_pii(text)) for page, text in segments]
        chunks = chunk_segments(segments)
        if not chunks:
            raise IngestionError("No indexable text found")
        if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
            raise IngestionError("The document is too large to index")

        vectors = embeddings.embed_documents([chunk.content for chunk in chunks])
        if len(vectors) != len(chunks):
            raise EmbeddingError("Embedding count does not match chunk count")

        _store(db, document, parsed, pii_by_segment, chunks, vectors)
    except (IngestionError, ParseError, StorageError, DecryptionError, EmbeddingError) as exc:
        if not isinstance(exc, (ParseError, IngestionError)):
            logger.error("Ingestion failed (%s): document=%s", type(exc).__name__, document.id)
        _mark_failed(db, document, _user_message(exc))
    except Exception:
        logger.exception("Unexpected ingestion failure: document=%s", document.id)
        _mark_failed(db, document, "Processing failed unexpectedly")
    return document