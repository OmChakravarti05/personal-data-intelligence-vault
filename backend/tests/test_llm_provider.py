import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.services import llm


@pytest.fixture(autouse=True)
def fresh_cache():
    llm.get_llm.cache_clear()
    yield
    llm.get_llm.cache_clear()


def test_default_provider_is_local_ollama():
    assert settings.llm_provider == "ollama"
    assert llm.is_external_provider() is False


def test_ollama_provider_builds_chat_ollama(monkeypatch):
    from langchain_ollama import ChatOllama

    monkeypatch.setattr(settings, "llm_provider", "ollama")
    assert isinstance(llm.get_llm(), ChatOllama)


def test_groq_without_key_is_unavailable_not_a_crash(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", None)
    with pytest.raises(llm.LLMUnavailable):
        llm.get_llm()


def test_groq_with_key_builds_chat_groq(monkeypatch):
    from langchain_groq import ChatGroq

    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", SecretStr("test-key-not-real"))
    assert llm.is_external_provider() is True
    assert isinstance(llm.get_llm(), ChatGroq)


def test_api_key_never_appears_in_settings_repr(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", SecretStr("test-key-not-real"))
    assert "test-key-not-real" not in repr(settings)
    assert "test-key-not-real" not in str(settings)