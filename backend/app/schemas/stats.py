from pydantic import BaseModel


class CategoryCount(BaseModel):
    category: str
    count: int


class StatsRead(BaseModel):
    documents_total: int
    documents_by_status: dict[str, int]
    storage_bytes: int
    chunks_total: int
    pii_findings_total: int
    documents_with_pii: int
    pii_by_category: list[CategoryCount]
    conversations_total: int
    messages_total: int