import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog

logger = logging.getLogger(__name__)

RESULT_SUCCESS = "success"
RESULT_FAILURE = "failure"

# Metadata keys containing any of these are dropped, so a careless caller
# cannot put secrets or document/question text into the log.
_FORBIDDEN_KEY_PARTS = (
    "password",
    "token",
    "secret",
    "key",
    "content",
    "text",
    "question",
    "answer",
    "authorization",
)
_MAX_VALUE_CHARS = 200


def safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metadata:
        return None
    clean: dict[str, Any] = {}
    for key, value in metadata.items():
        if any(part in key.lower() for part in _FORBIDDEN_KEY_PARTS):
            continue
        if isinstance(value, bool | int | float):
            clean[key] = value
        elif isinstance(value, str):
            clean[key] = value[:_MAX_VALUE_CHARS]
    return clean or None


def audit(
    db: Session,
    *,
    event_type: str,
    user_id: uuid.UUID | None = None,
    result: str = RESULT_SUCCESS,
    resource_type: str | None = None,
    resource_id: uuid.UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write one audit row and commit it. Never raises.

    This commits, so call it only when the session has no other pending
    changes: after the main commit, or before raising an error.
    """
    try:
        db.add(
            AuditLog(
                user_id=user_id,
                event_type=event_type,
                resource_type=resource_type,
                resource_id=str(resource_id)[:64] if resource_id else None,
                result=result,
                event_metadata=safe_metadata(metadata),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not write audit event: %s", event_type)