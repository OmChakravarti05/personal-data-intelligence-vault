import uuid

from pydantic import BaseModel


class SearchResult(BaseModel):
    """Deliberately excludes owner_id and storage_id."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    chunk_index: int
    excerpt: str
    distance: float


class SearchResponse(BaseModel):
    query: str
    count: int
    max_distance: float
    results: list[SearchResult]