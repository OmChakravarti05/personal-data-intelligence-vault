import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentRead(BaseModel):
    """Deliberately excludes storage_id, file_hash and owner_id."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    status: str
    error_message: str | None
    page_count: int | None
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None


class DocumentList(BaseModel):
    items: list[DocumentRead]
    total: int
    limit: int
    offset: int