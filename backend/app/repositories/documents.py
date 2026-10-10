import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document


def get_owned(db: Session, owner_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
    """The only way routes load a document: the owner filter is part of the query."""
    return db.scalar(
        select(Document).where(Document.id == document_id, Document.owner_id == owner_id)
    )


def find_by_hash(db: Session, owner_id: uuid.UUID, file_hash: str) -> Document | None:
    return db.scalar(
        select(Document).where(
            Document.owner_id == owner_id, Document.file_hash == file_hash
        )
    )


def list_owned(
    db: Session,
    owner_id: uuid.UUID,
    *,
    q: str | None,
    status: str | None,
    sort_column,
    descending: bool,
    limit: int,
    offset: int,
) -> tuple[list[Document], int]:
    conditions = [Document.owner_id == owner_id]
    if status:
        conditions.append(Document.status == status)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(Document.original_filename.ilike(f"%{escaped}%", escape="\\"))

    total = db.scalar(select(func.count()).select_from(Document).where(*conditions)) or 0
    order = sort_column.desc() if descending else sort_column.asc()
    items = db.scalars(
        select(Document)
        .where(*conditions)
        .order_by(order, Document.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(items), total