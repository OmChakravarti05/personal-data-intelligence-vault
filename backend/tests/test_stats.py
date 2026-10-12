from tests.test_auto_indexing import TEXT, indexing, make_user, upload  # noqa: F401
from tests.test_chat import ask, llm  # noqa: F401

PII_TEXT = "Please contact jane.doe@example.com about the budget review."


def stats(client, headers):
    response = client.get("/stats", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_stats_require_login(client):
    assert client.get("/stats").status_code == 401


def test_new_user_sees_zeros(client):
    body = stats(client, make_user(client))
    assert body["documents_total"] == 0
    assert body["documents_by_status"] == {
        "uploaded": 0,
        "processing": 0,
        "indexed": 0,
        "failed": 0,
    }
    assert body["chunks_total"] == 0 and body["pii_findings_total"] == 0
    assert body["conversations_total"] == 0 and body["messages_total"] == 0
    assert body["pii_by_category"] == []


def test_stats_reflect_an_indexed_document(client, indexing):
    headers = make_user(client)
    data = TEXT.encode()
    upload(client, headers, data=data)
    body = stats(client, headers)
    assert body["documents_total"] == 1
    assert body["documents_by_status"]["indexed"] == 1
    assert body["storage_bytes"] == len(data)
    assert body["chunks_total"] >= 1


def test_pii_findings_are_counted_without_values(client, indexing):
    headers = make_user(client)
    upload(client, headers, "contact.txt", PII_TEXT.encode())
    response = client.get("/stats", headers=headers)
    body = response.json()
    assert body["pii_findings_total"] >= 1
    assert body["documents_with_pii"] == 1
    assert body["pii_by_category"][0]["count"] >= 1
    assert "jane.doe" not in response.text


def test_stats_are_isolated_per_user(client, indexing):
    alice = make_user(client, "alice@example.com")
    bob = make_user(client, "bob@example.com")
    upload(client, alice, "contact.txt", PII_TEXT.encode())
    body = stats(client, bob)
    assert body["documents_total"] == 0 and body["pii_findings_total"] == 0
    assert stats(client, alice)["documents_total"] == 1


def test_chat_activity_is_counted(client, indexing, llm):
    headers = make_user(client)
    upload(client, headers)
    ask(client, headers)
    body = stats(client, headers)
    assert body["conversations_total"] == 1 and body["messages_total"] == 2