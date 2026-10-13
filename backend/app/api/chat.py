import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from langchain_core.embeddings import Embeddings
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import ChatMessage, Conversation, User
from app.schemas.chat import (
    AskRequest,
    AskResponse,
    ConversationDetail,
    ConversationRead,
    SourceRead,
)
from app.services.audit import RESULT_FAILURE, audit
from app.services.embeddings import get_embeddings
from app.services.llm import LLMUnavailable, get_llm
from app.services.rag import answer_question

router = APIRouter(prefix="/chat", tags=["chat"])

_EXCERPT_CHARS = 300
_TITLE_CHARS = 60


def _get_owned_or_404(db: Session, user: User, conversation_id: uuid.UUID) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.owner_id == user.id
        )
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


@router.post("/ask", response_model=AskResponse)
def ask(
    payload: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    embeddings: Embeddings = Depends(get_embeddings),
    llm=Depends(get_llm),
) -> AskResponse:
    conversation = None
    history: list[tuple[str, str]] = []
    if payload.conversation_id is not None:
        conversation = _get_owned_or_404(db, current_user, payload.conversation_id)
        history = [(m.role, m.content) for m in conversation.messages]

    try:
        result = answer_question(
            db, current_user.id, embeddings, llm, payload.question, history=history
        )
    except LLMUnavailable:
        audit(
            db,
            event_type="chat.ask",
            result=RESULT_FAILURE,
            user_id=current_user.id,
            metadata={"reason": "model_unavailable"},
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The assistant is not available right now. Please try again.",
        )

    sources = [
        SourceRead(
            number=s.number,
            document_id=s.hit.document_id,
            filename=s.hit.filename,
            page_number=s.hit.page_number,
            chunk_index=s.hit.chunk_index,
            excerpt=s.hit.content[:_EXCERPT_CHARS],
            distance=round(s.hit.distance, 4),
            cited=s.cited,
        )
        for s in result.sources
    ]

    if conversation is None:
        conversation = Conversation(
            owner_id=current_user.id, title=payload.question[:_TITLE_CHARS]
        )
        db.add(conversation)
        db.flush()

    # Both rows are written in one transaction, which would give them the same
    # server timestamp. Explicit times keep the question before the answer.
    now = datetime.now(timezone.utc)
    db.add(
        ChatMessage(
            conversation_id=conversation.id,
            owner_id=current_user.id,
            role="user",
            content=payload.question,
            created_at=now,
        )
    )
    reply = ChatMessage(
        conversation_id=conversation.id,
        owner_id=current_user.id,
        role="assistant",
        content=result.answer,
        sources=[s.model_dump(mode="json") for s in sources],
        created_at=now + timedelta(milliseconds=1),
    )
    db.add(reply)
    conversation.updated_at = now
    db.commit()

    response = AskResponse(
        conversation_id=conversation.id,
        message_id=reply.id,
        answer=result.answer,
        grounded=result.grounded,
        sources=sources,
    )
    audit(
        db,
        event_type="chat.ask",
        user_id=current_user.id,
        resource_type="conversation",
        resource_id=conversation.id,
        metadata={"grounded": result.grounded, "sources": len(sources)},
    )
    return response


@router.get("/conversations", response_model=list[ConversationRead])
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Conversation]:
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.owner_id == current_user.id)
            .order_by(Conversation.updated_at.desc())
            .limit(50)
        )
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Conversation:
    return _get_owned_or_404(db, current_user, conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    conversation = _get_owned_or_404(db, current_user, conversation_id)
    db.delete(conversation)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)