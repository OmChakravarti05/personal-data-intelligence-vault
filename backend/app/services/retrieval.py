import uuid
from dataclasses import dataclass

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document as LCDocument
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk, DocumentPermission, DocumentStatus


@dataclass(frozen=True)
class SearchHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk_index: int
    page_number: int | None
    content: str
    distance: float  # cosine distance: 0 is identical, larger is less related


def search_chunks(
    db: Session,
    owner_id: uuid.UUID,
    embeddings: Embeddings,
    query: str,
    *,
    top_k: int = 5,
    max_distance: float | None = None,
    document_ids: list[uuid.UUID] | None = None,
) -> list[SearchHit]:
    """Semantic search over the documents ONE user may read.

    `owner_id` is the searching user. They may read indexed documents they own,
    plus indexed documents another user has shared with them (read permission).
    The access rule is part of the SQL query, so other chunks are never ranked,
    loaded or returned. Nothing here depends on a prompt for security.
    """
    if not query.strip():
        return []

    query_vector = embeddings.embed_query(query)
    distance = DocumentChunk.embedding.cosine_distance(query_vector)

    shared_with_user = select(DocumentPermission.document_id).where(
        DocumentPermission.grantee_id == owner_id
    )
    can_read = or_(Document.owner_id == owner_id, Document.id.in_(shared_with_user))

    statement = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            Document.original_filename,
            DocumentChunk.chunk_index,
            DocumentChunk.page_number,
            DocumentChunk.content,
            distance.label("distance"),
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            can_read,
            DocumentChunk.owner_id == Document.owner_id,
            Document.status == DocumentStatus.INDEXED,
        )
    )
    if document_ids:
        statement = statement.where(DocumentChunk.document_id.in_(document_ids))
    if max_distance is not None:
        statement = statement.where(distance <= max_distance)
    statement = statement.order_by(distance).limit(top_k)

    # The HNSW index applies filters after its approximate scan. Iterative scan
    # keeps scanning until enough rows pass the access filter, so results are not
    # starved when many users share the table.
    db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    rows = db.execute(statement).all()

    return [
        SearchHit(
            chunk_id=row.id,
            document_id=row.document_id,
            filename=row.original_filename,
            chunk_index=row.chunk_index,
            page_number=row.page_number,
            content=row.content,
            distance=float(row.distance),
        )
        for row in rows
    ]


class UserScopedRetriever(BaseRetriever):
    """LangChain retriever that can only ever see documents one user may read."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    db: Session
    owner_id: uuid.UUID
    embeddings: Embeddings
    top_k: int = Field(default=5, ge=1, le=20)
    max_distance: float | None = None
    document_ids: list[uuid.UUID] | None = None

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[LCDocument]:
        hits = search_chunks(
            self.db,
            self.owner_id,
            self.embeddings,
            query,
            top_k=self.top_k,
            max_distance=self.max_distance,
            document_ids=self.document_ids,
        )
        # Metadata deliberately leaves out owner ids and storage ids.
        return [
            LCDocument(
                page_content=hit.content,
                metadata={
                    "chunk_id": str(hit.chunk_id),
                    "document_id": str(hit.document_id),
                    "filename": hit.filename,
                    "chunk_index": hit.chunk_index,
                    "page_number": hit.page_number,
                    "distance": round(hit.distance, 4),
                },
            )
            for hit in hits
        ]