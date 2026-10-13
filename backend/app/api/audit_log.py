from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import AuditLog, User
from app.schemas.audit import AuditEventList

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditEventList)
def list_audit_events(
    event_type: str | None = Query(None, max_length=50),
    result: Literal["success", "failure"] | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AuditEventList:
    """The signed-in user's own security events, newest first."""
    conditions = [AuditLog.user_id == current_user.id]
    if event_type:
        conditions.append(AuditLog.event_type == event_type)
    if result:
        conditions.append(AuditLog.result == result)

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conditions))
    items = db.scalars(
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return AuditEventList(items=items, total=total or 0, limit=limit, offset=offset)