import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PIIFinding


def get_owned(db: Session, owner_id: uuid.UUID, finding_id: uuid.UUID) -> PIIFinding | None:
    return db.scalar(
        select(PIIFinding).where(
            PIIFinding.id == finding_id, PIIFinding.owner_id == owner_id
        )
    )


def list_owned(
    db: Session,
    owner_id: uuid.UUID,
    *,
    document_id: uuid.UUID | None,
    category: str | None,
    limit: int,
    offset: int,
) -> tuple[list[PIIFinding], int]:
    conditions = [PIIFinding.owner_id == owner_id]
    if document_id:
        conditions.append(PIIFinding.document_id == document_id)
    if category:
        conditions.append(PIIFinding.category == category.upper())

    total = db.scalar(select(func.count()).select_from(PIIFinding).where(*conditions)) or 0
    items = db.scalars(
        select(PIIFinding)
        .where(*conditions)
        .order_by(PIIFinding.created_at.desc(), PIIFinding.start_char, PIIFinding.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(items), total