import logging
import uuid
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Document, DocumentStatus, PIIFinding, User
from app.repositories import documents as documents_repo
from app.repositories import pii as pii_repo
from app.schemas.pii import (
    PIIFindingList,
    PIIFindingRead,
    PIIPreview,
    PIIPreviewSegment,
    PIIScanResult,
)
from app.services.document_parser import ParseError
from app.services.encryption import DecryptionError
from app.services.pii_scanner import build_redacted_preview, scan_document
from app.services.storage import StorageBackend, StorageError, get_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pii", tags=["pii"])


def _owned_document_or_404(db: Session, user: User, document_id: uuid.UUID) -> Document:
    document = documents_repo.get_owned(db, user.id, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


def _require_readable(document: Document) -> None:
    if document.status == DocumentStatus.FAILED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This document could not be processed, so it cannot be scanned",
        )


def _translate_errors(exc: Exception, document: Document) -> HTTPException:
    if isinstance(exc, StorageError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    if isinstance(exc, ParseError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    logger.error("Stored file failed integrity check: document=%s", document.id)
    return HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "The stored file could not be read"
    )


_FILE_ERRORS = (StorageError, DecryptionError, ParseError)


@router.get("/findings", response_model=PIIFindingList)
def list_findings(
    document_id: uuid.UUID | None = None,
    category: str | None = Query(None, max_length=50),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PIIFindingList:
    if document_id is not None:
        _owned_document_or_404(db, current_user, document_id)
    items, total = pii_repo.list_owned(
        db,
        current_user.id,
        document_id=document_id,
        category=category,
        limit=limit,
        offset=offset,
    )
    return PIIFindingList(items=items, total=total, limit=limit, offset=offset)


@router.get("/findings/{finding_id}", response_model=PIIFindingRead)
def get_finding(
    finding_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PIIFinding:
    finding = pii_repo.get_owned(db, current_user.id, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return finding


@router.post("/scan/{document_id}", response_model=PIIScanResult)
def scan(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
) -> PIIScanResult:
    document = _owned_document_or_404(db, current_user, document_id)
    _require_readable(document)
    try:
        findings = scan_document(db, storage, document)
    except _FILE_ERRORS as exc:
        raise _translate_errors(exc, document)
    counts = Counter(finding.category for finding in findings)
    return PIIScanResult(
        document_id=document.id,
        total_findings=len(findings),
        by_category=dict(counts),
    )


@router.get("/preview/{document_id}", response_model=PIIPreview)
def redacted_preview(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
) -> PIIPreview:
    document = _owned_document_or_404(db, current_user, document_id)
    _require_readable(document)
    try:
        segments, truncated = build_redacted_preview(storage, document)
    except _FILE_ERRORS as exc:
        raise _translate_errors(exc, document)
    return PIIPreview(
        document_id=document.id,
        segments=[PIIPreviewSegment(page_number=p, text=t) for p, t in segments],
        truncated=truncated,
    )