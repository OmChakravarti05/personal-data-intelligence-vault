import logging
from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """The language model could not be reached or is not configured."""


def is_external_provider() -> bool:
    """True when questions and retrieved passages leave this machine."""
    return settings.llm_provider == "groq"


@lru_cache
def get_llm() -> BaseChatModel:
    if settings.llm_provider == "groq":
        if settings.groq_api_key is None:
            logger.error("LLM_PROVIDER=groq but GROQ_API_KEY is not set")
            raise LLMUnavailable("The language model is not configured")
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key.get_secret_value(),
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
            max_retries=1,
        )

    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=settings.llm_model,
        base_url=settings.ollama_base_url,
        temperature=settings.llm_temperature,
        client_kwargs={"timeout": settings.llm_timeout_seconds},
    )