import logging
import uuid
from collections.abc import Callable

from langchain_core.embeddings import Embeddings
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Document
from app.services.embeddings import get_embeddings
from app.services.ingestion import IngestionBusy, ingest_document
from app.services.storage import StorageBackend, get_storage

logger = logging.getLogger(__name__)

Indexer = Callable[[uuid.UUID], None]


def ingest_by_id(
    document_id: uuid.UUID,
    *,
    session_factory: Callable[[], Session],
    storage: StorageBackend,
    embeddings: Embeddings,
) -> None:
    """Index one document in its own database session. Never raises.

    A background job cannot reuse the request's session, because that session
    is closed as soon as the response is sent.
    """
    db = session_factory()
    try:
        document = db.get(Document, document_id)
        if document is None:  # deleted before the job started
            return
        ingest_document(db, storage, embeddings, document)
    except IngestionBusy:
        logger.info("Document already being processed: %s", document_id)
    except Exception:
        logger.exception("Background indexing failed: document=%s", document_id)
    finally:
        db.close()


def get_indexer() -> Indexer:
    """FastAPI dependency. Tests replace it, so they never touch the real model."""

    def run(document_id: uuid.UUID) -> None:
        ingest_by_id(
            document_id,
            session_factory=SessionLocal,
            storage=get_storage(),
            embeddings=get_embeddings(),
        )

    return run