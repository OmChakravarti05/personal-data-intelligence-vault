import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from langchain_core.embeddings import Embeddings
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import User
from app.repositories import documents as documents_repo
from app.schemas.search import SearchResponse, SearchResult
from app.services.embeddings import EmbeddingError, get_embeddings
from app.services.retrieval import search_chunks

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, max_length=500, description="Search question"),
    top_k: int = Query(settings.retrieval_top_k, ge=1, le=20),
    document_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embeddings: Embeddings = Depends(get_embeddings),
) -> SearchResponse:
    """Semantic search over the current user's indexed documents only."""
    if document_id is not None and documents_repo.get_owned(db, current_user.id, document_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    try:
        hits = search_chunks(
            db,
            current_user.id,
            embeddings,
            q,
            top_k=top_k,
            max_distance=settings.retrieval_max_distance,
            document_ids=[document_id] if document_id else None,
        )
    except EmbeddingError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Search is temporarily unavailable"
        )

    return SearchResponse(
        query=q,
        count=len(hits),
        max_distance=settings.retrieval_max_distance,
        results=[
            SearchResult(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                filename=hit.filename,
                page_number=hit.page_number,
                chunk_index=hit.chunk_index,
                excerpt=hit.content,
                distance=round(hit.distance, 4),
            )
            for hit in hits
        ],
    )