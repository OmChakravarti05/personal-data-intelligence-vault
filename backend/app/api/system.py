from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.config import settings
from app.services.llm import is_external_provider

router = APIRouter(prefix="/system", tags=["system"])


class SystemInfo(BaseModel):
    llm_provider: str
    llm_model: str
    external_llm: bool


@router.get("/info", response_model=SystemInfo)
def system_info(_user=Depends(get_current_user)) -> SystemInfo:
    """Which language model answers questions, and whether text leaves this machine.
    Never returns any secret."""
    model = settings.groq_model if is_external_provider() else settings.llm_model
    return SystemInfo(
        llm_provider=settings.llm_provider,
        llm_model=model,
        external_llm=is_external_provider(),
    )