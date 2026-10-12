from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import (
    ChatMessage,
    Conversation,
    Document,
    DocumentChunk,
    DocumentStatus,
    PIIFinding,
    User,
)
from app.schemas.stats import CategoryCount, StatsRead

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=StatsRead)
def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StatsRead:
    owner = current_user.id

    by_status = {name: 0 for name in DocumentStatus.ALL}
    for name, count in db.execute(
        select(Document.status, func.count())
        .where(Document.owner_id == owner)
        .group_by(Document.status)
    ):
        by_status[name] = count

    storage_bytes = db.scalar(
        select(func.coalesce(func.sum(Document.size_bytes), 0)).where(Document.owner_id == owner)
    )
    chunks_total = db.scalar(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.owner_id == owner)
    )
    pii_rows = db.execute(
        select(PIIFinding.category, func.count())
        .where(PIIFinding.owner_id == owner)
        .group_by(PIIFinding.category)
        .order_by(func.count().desc(), PIIFinding.category)
    ).all()
    documents_with_pii = db.scalar(
        select(func.count(distinct(PIIFinding.document_id))).where(PIIFinding.owner_id == owner)
    )
    conversations_total = db.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.owner_id == owner)
    )
    messages_total = db.scalar(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.owner_id == owner)
    )

    return StatsRead(
        documents_total=sum(by_status.values()),
        documents_by_status=by_status,
        storage_bytes=int(storage_bytes or 0),
        chunks_total=int(chunks_total or 0),
        pii_findings_total=sum(count for _, count in pii_rows),
        documents_with_pii=int(documents_with_pii or 0),
        pii_by_category=[CategoryCount(category=c, count=n) for c, n in pii_rows],
        conversations_total=int(conversations_total or 0),
        messages_total=int(messages_total or 0),
    )