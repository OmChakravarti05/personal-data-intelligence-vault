import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ShareCreate(BaseModel):
    document_id: uuid.UUID
    email: str = Field(min_length=3, max_length=255)


class ShareRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    grantee_email: str
    grantee_name: str
    permission: str
    created_at: datetime


class SharedWithMeRead(BaseModel):
    share_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    status: str
    page_count: int | None
    shared_by: str
    shared_by_email: str
    shared_at: datetime