import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Document, DocumentPermission, User
from app.repositories import documents as repo
from app.schemas.share import ShareCreate, ShareRead, SharedWithMeRead
from app.services.audit import audit

router = APIRouter(prefix="/shares", tags=["shares"])


def _share_read(share: DocumentPermission, grantee: User) -> ShareRead:
    return ShareRead(
        id=share.id,
        document_id=share.document_id,
        grantee_email=grantee.email,
        grantee_name=grantee.full_name,
        permission=share.permission,
        created_at=share.created_at,
    )


@router.post("", response_model=ShareRead, status_code=status.HTTP_201_CREATED)
def create_share(
    payload: ShareCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShareRead:
    document = repo.get_owned(db, current_user.id, payload.document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    grantee = db.scalar(
        select(User).where(
            User.email == payload.email.strip().lower(), User.is_active.is_(True)
        )
    )
    if grantee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if grantee.id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You already own this document")

    share = DocumentPermission(
        document_id=document.id,
        grantee_id=grantee.id,
        granted_by=current_user.id,
        permission="read",
    )
    db.add(share)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Already shared with this user")
    db.refresh(share)

    response = _share_read(share, grantee)
    audit(
        db,
        event_type="share.grant",
        user_id=current_user.id,
        resource_type="document",
        resource_id=document.id,
        metadata={"grantee_id": str(grantee.id)},
    )
    return response


@router.get("/document/{document_id}", response_model=list[ShareRead])
def list_document_shares(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ShareRead]:
    """Who a document is shared with. Owner only."""
    document = repo.get_owned(db, current_user.id, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    rows = db.execute(
        select(DocumentPermission, User)
        .join(User, User.id == DocumentPermission.grantee_id)
        .where(DocumentPermission.document_id == document.id)
        .order_by(DocumentPermission.created_at)
    ).all()
    return [_share_read(share, grantee) for share, grantee in rows]


@router.get("/with-me", response_model=list[SharedWithMeRead])
def list_shared_with_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SharedWithMeRead]:
    rows = db.execute(
        select(DocumentPermission, Document, User)
        .join(Document, Document.id == DocumentPermission.document_id)
        .join(User, User.id == Document.owner_id)
        .where(DocumentPermission.grantee_id == current_user.id)
        .order_by(DocumentPermission.created_at.desc())
    ).all()
    return [
        SharedWithMeRead(
            share_id=share.id,
            document_id=document.id,
            filename=document.original_filename,
            mime_type=document.mime_type,
            size_bytes=document.size_bytes,
            status=document.status,
            page_count=document.page_count,
            shared_by=owner.full_name,
            shared_by_email=owner.email,
            shared_at=share.created_at,
        )
        for share, document, owner in rows
    ]


@router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_share(
    share_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Revoke a share. Allowed for the document owner, or for the grantee leaving."""
    row = db.execute(
        select(DocumentPermission, Document)
        .join(Document, Document.id == DocumentPermission.document_id)
        .where(
            DocumentPermission.id == share_id,
            or_(
                Document.owner_id == current_user.id,
                DocumentPermission.grantee_id == current_user.id,
            ),
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share not found")

    share, document = row
    by = "owner" if document.owner_id == current_user.id else "grantee"
    document_id, grantee_id = document.id, share.grantee_id
    db.delete(share)
    db.commit()
    audit(
        db,
        event_type="share.revoke",
        user_id=current_user.id,
        resource_type="document",
        resource_id=document_id,
        metadata={"grantee_id": str(grantee_id), "by": by},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)