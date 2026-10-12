import pytest
from langchain_core.messages import AIMessage

from app.main import app
from app.services.llm import get_llm
from tests.test_auto_indexing import TEXT, indexing, make_user, upload  # noqa: F401


class FakeLLM:
    def __init__(self, reply="Budget notes were reviewed [1]."):
        self.reply = reply
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.reply)


class BrokenLLM:
    def invoke(self, messages):
        raise ConnectionError("ollama is down")


@pytest.fixture
def llm():
    fake = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_llm, None)


def ask(client, headers, question=TEXT, conversation_id=None):
    body = {"question": question}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return client.post("/chat/ask", headers=headers, json=body)


def test_ask_requires_login(client, llm):
    assert ask(client, {}).status_code == 401


def test_ask_returns_cited_answer_and_stores_conversation(client, indexing, llm):
    headers = make_user(client)
    upload(client, headers)
    response = ask(client, headers)
    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["answer"] == "Budget notes were reviewed [1]."
    assert body["sources"][0]["filename"] == "notes.txt"
    assert body["sources"][0]["cited"] is True

    detail = client.get(f"/chat/conversations/{body['conversation_id']}", headers=headers).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["sources"][0]["filename"] == "notes.txt"
    assert detail["title"] == TEXT[:60]


def test_follow_up_continues_the_conversation_with_history(client, indexing, llm):
    headers = make_user(client)
    upload(client, headers)
    first = ask(client, headers).json()
    second = ask(client, headers, conversation_id=first["conversation_id"]).json()
    assert second["conversation_id"] == first["conversation_id"]
    detail = client.get(f"/chat/conversations/{first['conversation_id']}", headers=headers).json()
    assert len(detail["messages"]) == 4
    # system + 2 earlier turns + the new question
    assert len(llm.calls[-1]) == 4


def test_unrelated_question_skips_the_model_but_is_stored(client, indexing, llm):
    headers = make_user(client)
    response = ask(client, headers, "What is in my files?")
    body = response.json()
    assert body["grounded"] is False and body["sources"] == []
    assert body["answer"] == "I couldn't find this in your documents."
    assert llm.calls == []
    assert len(client.get("/chat/conversations", headers=headers).json()) == 1


def test_other_users_documents_are_never_used(client, indexing, llm):
    alice = make_user(client, "alice@example.com")
    bob = make_user(client, "bob@example.com")
    upload(client, bob)
    body = ask(client, alice).json()
    assert body["grounded"] is False and llm.calls == []


def test_other_user_cannot_read_continue_or_delete_a_conversation(client, indexing, llm):
    alice = make_user(client, "alice@example.com")
    bob = make_user(client, "bob@example.com")
    upload(client, alice)
    conversation_id = ask(client, alice).json()["conversation_id"]

    assert client.get(f"/chat/conversations/{conversation_id}", headers=bob).status_code == 404
    assert ask(client, bob, conversation_id=conversation_id).status_code == 404
    assert client.delete(f"/chat/conversations/{conversation_id}", headers=bob).status_code == 404
    assert client.get("/chat/conversations", headers=bob).json() == []
    assert client.get(f"/chat/conversations/{conversation_id}", headers=alice).status_code == 200


def test_model_failure_returns_503_and_stores_nothing(client, indexing):
    headers = make_user(client)
    upload(client, headers)
    app.dependency_overrides[get_llm] = lambda: BrokenLLM()
    try:
        response = ask(client, headers)
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert response.status_code == 503
    assert "ollama" not in response.text
    assert client.get("/chat/conversations", headers=headers).json() == []


def test_blank_question_is_rejected(client, llm):
    headers = make_user(client)
    assert ask(client, headers, "   ").status_code == 422


def test_delete_conversation(client, indexing, llm):
    headers = make_user(client)
    upload(client, headers)
    conversation_id = ask(client, headers).json()["conversation_id"]
    assert client.delete(f"/chat/conversations/{conversation_id}", headers=headers).status_code == 204
    assert client.get(f"/chat/conversations/{conversation_id}", headers=headers).status_code == 404