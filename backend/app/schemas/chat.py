import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AskRequest(BaseModel):
    question: str = Field(max_length=2000)
    conversation_id: uuid.UUID | None = None

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be empty")
        return value


class SourceRead(BaseModel):
    number: int
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    chunk_index: int
    excerpt: str
    distance: float
    cited: bool


class AskResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    grounded: bool
    sources: list[SourceRead]


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    sources: list[dict] | None
    created_at: datetime


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead]