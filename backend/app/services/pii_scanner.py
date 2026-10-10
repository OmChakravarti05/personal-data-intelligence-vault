from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Document, PIIFinding
from app.services.document_parser import ExtractedDocument, parse_document
from app.services.pii_detection import detect_pii, redact_text
from app.services.storage import StorageBackend

PREVIEW_MAX_CHARS = 20_000


def extension_of(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1]


def pii_segments(parsed: ExtractedDocument) -> list[tuple[int | None, str]]:
    """Text units that offsets refer to: one per PDF page, or one for the whole file."""
    if any(page.page_number is not None for page in parsed.pages):
        return [(page.page_number, page.text) for page in parsed.pages]
    return [(None, "\n\n".join(page.text for page in parsed.pages))]


def _load(storage: StorageBackend, document: Document) -> ExtractedDocument:
    data = storage.read(document.storage_id)
    return parse_document(data, extension_of(document.original_filename))


def scan_document(
    db: Session, storage: StorageBackend, document: Document
) -> list[PIIFinding]:
    """Detect PII and replace this document's stored findings (safe to re-run)."""
    parsed = _load(storage, document)
    findings = [
        PIIFinding(
            document_id=document.id,
            owner_id=document.owner_id,
            category=match.category,
            start_char=match.start,
            end_char=match.end,
            page_number=page_number,
            confidence=match.score,
        )
        for page_number, text in pii_segments(parsed)
        for match in detect_pii(text)
    ]
    try:
        db.execute(
            delete(PIIFinding).where(
                PIIFinding.document_id == document.id,
                PIIFinding.owner_id == document.owner_id,
            )
        )
        db.add_all(findings)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return findings


def build_redacted_preview(
    storage: StorageBackend, document: Document, max_chars: int = PREVIEW_MAX_CHARS
) -> tuple[list[tuple[int | None, str]], bool]:
    """Redact first, then truncate, so cutting the text can never expose a value."""
    parsed = _load(storage, document)
    segments: list[tuple[int | None, str]] = []
    remaining, truncated = max_chars, False
    for page_number, text in pii_segments(parsed):
        if remaining <= 0:
            truncated = True
            break
        redacted = redact_text(text, detect_pii(text))
        if len(redacted) > remaining:
            redacted, truncated = redacted[:remaining], True
        remaining -= len(redacted)
        segments.append((page_number, redacted))
    return segments, truncated