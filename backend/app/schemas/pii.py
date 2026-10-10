import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

DISCLAIMER = (
    "Automated detection can miss sensitive data (false negatives) and flag "
    "harmless text (false positives). It does not guarantee privacy."
)


class PIIFindingRead(BaseModel):
    """Position and category only. The detected value itself is never stored."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    category: str
    start_char: int
    end_char: int
    page_number: int | None
    confidence: float
    created_at: datetime


class PIIFindingList(BaseModel):
    items: list[PIIFindingRead]
    total: int
    limit: int
    offset: int


class PIIScanResult(BaseModel):
    document_id: uuid.UUID
    total_findings: int
    by_category: dict[str, int]
    disclaimer: str = DISCLAIMER


class PIIPreviewSegment(BaseModel):
    page_number: int | None
    text: str


class PIIPreview(BaseModel):
    document_id: uuid.UUID
    segments: list[PIIPreviewSegment]
    truncated: bool
    disclaimer: str = DISCLAIMER