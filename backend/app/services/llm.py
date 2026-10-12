from functools import lru_cache

from langchain_ollama import ChatOllama

from app.core.config import settings


class LLMUnavailable(Exception):
    """The language model could not produce an answer (not running, timed out, empty)."""


@lru_cache
def get_llm() -> ChatOllama:
    return ChatOllama(
        model=settings.llm_model,
        base_url=settings.ollama_base_url,
        temperature=settings.llm_temperature,
        client_kwargs={"timeout": settings.llm_timeout_seconds},
    )