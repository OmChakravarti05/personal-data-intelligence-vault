import hashlib
import logging
import uuid
from typing import Literal
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from langchain_core.embeddings import Embeddings
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import Document, DocumentStatus, User
from app.repositories import documents as repo
from app.schemas.document import DocumentList, DocumentRead
from app.services.document_parser import ParseError, parse_document
from app.services.embeddings import get_embeddings
from app.services.encryption import DecryptionError
from app.services.file_validation import UploadValidationError, validate_upload
from app.services.ingestion import IngestionBusy, ingest_document
from app.services.storage import (
    StorageBackend,
    StorageError,
    get_storage,
    new_storage_id,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

_READ_CHUNK = 1024 * 1024
_SORT_COLUMNS = {
    "created_at": Document.created_at,
    "name": Document.original_filename,
    "size": Document.size_bytes,
}


def _read_limited(upload: UploadFile) -> bytes:
    """Read the upload in chunks and stop as soon as it exceeds the size limit."""
    buffer = bytearray()
    while chunk := upload.file.read(_READ_CHUNK):
        buffer.extend(chunk)
        if len(buffer) > settings.max_upload_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"File exceeds the {settings.max_upload_mb} MB limit",
            )
    return bytes(buffer)


def _get_owned_or_404(db: Session, user: User, document_id: uuid.UUID) -> Document:
    document = repo.get_owned(db, user.id, document_id)
    if document is None:
        # Same 404 whether the id doesn't exist or belongs to someone else.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


def _read_stored_file(storage: StorageBackend, document: Document) -> bytes:
    try:
        return storage.read(document.storage_id)
    except StorageError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    except DecryptionError:
        logger.error("Stored file failed integrity check: document=%s", document.id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "The stored file could not be read"
        )


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
) -> Document:
    data = _read_limited(file)
    try:
        name, extension, mime = validate_upload(file.filename, file.content_type, data)
    except UploadValidationError as exc:
        raise HTTPException(exc.status_code, str(exc))

    file_hash = hashlib.sha256(data).hexdigest()
    if repo.find_by_hash(db, current_user.id, file_hash):
        raise HTTPException(status.HTTP_409_CONFLICT, "You have already uploaded this file")

    storage_id = new_storage_id()
    document = Document(
        owner_id=current_user.id,
        original_filename=name,
        storage_id=storage_id,
        mime_type=mime,
        size_bytes=len(data),
        file_hash=file_hash,
    )

    # Extraction check. Status stays "uploaded" on success: only the full
    # ingestion pipeline is allowed to mark a document "indexed".
    try:
        document.page_count = parse_document(data, extension).page_count
    except ParseError as exc:
        document.status = DocumentStatus.FAILED
        document.error_message = str(exc)

    storage.save(storage_id, data)
    db.add(document)
    try:
        db.commit()
    except IntegrityError:  # same file uploaded twice at the same moment
        db.rollback()
        storage.delete(storage_id)
        raise HTTPException(status.HTTP_409_CONFLICT, "You have already uploaded this file")
    except Exception:
        db.rollback()
        storage.delete(storage_id)  # never leave an orphaned encrypted file
        raise
    db.refresh(document)
    return document


@router.get("", response_model=DocumentList)
def list_documents(
    q: str | None = Query(None, max_length=100, description="Filename search"),
    status_filter: Literal["uploaded", "processing", "indexed", "failed"] | None = Query(
        None, alias="status"
    ),
    sort: Literal["created_at", "name", "size"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentList:
    items, total = repo.list_owned(
        db,
        current_user.id,
        q=q,
        status=status_filter,
        sort_column=_SORT_COLUMNS[sort],
        descending=(order == "desc"),
        limit=limit,
        offset=offset,
    )
    return DocumentList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Document:
    return _get_owned_or_404(db, current_user, document_id)


@router.get("/{document_id}/download")
def download_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
) -> Response:
    document = _get_owned_or_404(db, current_user, document_id)
    data = _read_stored_file(storage, document)
    return Response(
        content=data,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(document.original_filename)}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
) -> Response:
    document = _get_owned_or_404(db, current_user, document_id)
    storage_id = document.storage_id
    db.delete(document)  # chunks and PII findings are removed by ON DELETE CASCADE
    db.commit()
    try:
        storage.delete(storage_id)
    except OSError:
        logger.error("Could not remove stored file after delete: %s", storage_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{document_id}/reprocess", response_model=DocumentRead)
def reprocess_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
    embeddings: Embeddings = Depends(get_embeddings),
) -> Document:
    """Run the full ingestion pipeline again: extract, scan, chunk, embed, store.

    The document is marked "indexed" only if every step succeeds. A failure
    leaves it "failed" with a safe message.
    """
    document = _get_owned_or_404(db, current_user, document_id)
    try:
        return ingest_document(db, storage, embeddings, document, force=True)
    except IngestionBusy:
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is already being processed")