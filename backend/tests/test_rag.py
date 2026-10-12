import pytest
from langchain_core.messages import AIMessage

from app.models import DocumentStatus
from app.services.llm import LLMUnavailable
from app.services.rag import MAX_HISTORY_MESSAGES, NO_ANSWER, answer_question
from tests.fakes import FakeEmbeddings
from tests.test_retrieval import add_chunk, make_document, make_user


class FakeLLM:
    def __init__(self, reply="Rent is due on the first [1]."):
        self.reply = reply
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.reply)


class BrokenLLM:
    def invoke(self, messages):
        raise ConnectionError("ollama is down")


@pytest.fixture
def embedder():
    return FakeEmbeddings()


@pytest.fixture
def owner(db_session):
    return make_user(db_session)


def seed(db, owner, embedder, text="Rent is due on the first of every month."):
    document = make_document(db, owner, name="lease.txt", status=DocumentStatus.INDEXED)
    add_chunk(db, document, 0, text, embedder)
    return text


def ask(db, owner, embedder, llm, question, **kwargs):
    return answer_question(db, owner.id, embedder, llm, question, **kwargs)


def test_grounded_answer_returns_cited_sources(db_session, owner, embedder):
    text = seed(db_session, owner, embedder)
    llm = FakeLLM()
    result = ask(db_session, owner, embedder, llm, text)
    assert result.grounded and result.answer == "Rent is due on the first [1]."
    assert len(result.sources) == 1
    assert result.sources[0].hit.filename == "lease.txt"
    assert result.sources[0].cited is True
    prompt = llm.calls[0][-1].content
    assert text in prompt and "<context>" in prompt


def test_uncited_passages_are_marked_not_cited(db_session, owner, embedder):
    text = seed(db_session, owner, embedder)
    result = ask(db_session, owner, embedder, FakeLLM("It is due monthly."), text)
    assert result.sources[0].cited is False


def test_no_documents_means_no_llm_call(db_session, owner, embedder):
    llm = FakeLLM()
    result = ask(db_session, owner, embedder, llm, "What is my rent?")
    assert result.answer == NO_ANSWER and result.grounded is False and result.sources == []
    assert llm.calls == []


def test_other_users_text_never_reaches_the_prompt(db_session, owner, embedder):
    bob = make_user(db_session, "bob@example.com")
    secret = "Bob confidential salary negotiation notes."
    seed(db_session, bob, embedder, secret)
    llm = FakeLLM()
    result = ask(db_session, owner, embedder, llm, secret)
    assert result.grounded is False
    assert llm.calls == []


def test_unindexed_documents_are_not_used(db_session, owner, embedder):
    document = make_document(db_session, owner, status=DocumentStatus.FAILED)
    add_chunk(db_session, document, 0, "Half processed text.", embedder)
    llm = FakeLLM()
    result = ask(db_session, owner, embedder, llm, "Half processed text.")
    assert result.grounded is False and llm.calls == []


def test_llm_failure_raises_safe_error(db_session, owner, embedder):
    text = seed(db_session, owner, embedder)
    with pytest.raises(LLMUnavailable) as error:
        ask(db_session, owner, embedder, BrokenLLM(), text)
    assert "ollama is down" not in str(error.value)


def test_empty_llm_reply_is_an_error(db_session, owner, embedder):
    text = seed(db_session, owner, embedder)
    with pytest.raises(LLMUnavailable):
        ask(db_session, owner, embedder, FakeLLM("   "), text)


def test_history_is_included_and_trimmed(db_session, owner, embedder):
    text = seed(db_session, owner, embedder)
    history = [("user" if i % 2 == 0 else "assistant", f"turn {i}") for i in range(20)]
    llm = FakeLLM()
    ask(db_session, owner, embedder, llm, text, history=history)
    messages = llm.calls[0]
    assert len(messages) == 1 + MAX_HISTORY_MESSAGES + 1
    assert messages[1].content == "turn 14"

def test_model_saying_not_found_returns_no_sources(db_session, owner, embedder):
    text = seed(db_session, owner, embedder)
    result = ask(db_session, owner, embedder, FakeLLM(NO_ANSWER), text)
    assert result.answer == NO_ANSWER
    assert result.grounded is False and result.sources == []