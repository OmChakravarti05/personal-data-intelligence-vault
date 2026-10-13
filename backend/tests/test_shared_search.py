from tests.test_auto_indexing import TEXT, indexing, make_user, upload  # noqa: F401
from tests.test_chat import ask, llm  # noqa: F401
from tests.test_shares import share

OTHER = b"Confidential salary negotiation plan."


def search(client, headers, query=TEXT):
    response = client.get("/search", headers=headers, params={"q": query})
    assert response.status_code == 200
    return response.json()["results"]


def alice_and_bob(client):
    alice = make_user(client, "alice@example.com")
    bob = make_user(client, "bob@example.com")
    doc_id = upload(client, alice).json()["id"]
    return alice, bob, doc_id


def test_search_follows_share_and_revoke(client, indexing):
    alice, bob, doc_id = alice_and_bob(client)
    assert search(client, bob) == []

    share_id = share(client, alice, doc_id, "bob@example.com").json()["id"]
    assert [hit["filename"] for hit in search(client, bob)] == ["notes.txt"]

    client.delete(f"/shares/{share_id}", headers=alice)
    assert search(client, bob) == []


def test_sharing_one_document_does_not_expose_others(client, indexing):
    alice, bob, doc_id = alice_and_bob(client)
    upload(client, alice, "salary.txt", OTHER)
    share(client, alice, doc_id, "bob@example.com")
    assert search(client, bob, OTHER.decode()) == []
    assert [hit["filename"] for hit in search(client, alice, OTHER.decode())] == ["salary.txt"]


def test_chat_uses_shared_documents_only_while_shared(client, indexing, llm):
    alice, bob, doc_id = alice_and_bob(client)
    assert ask(client, bob).json()["grounded"] is False

    share_id = share(client, alice, doc_id, "bob@example.com").json()["id"]
    shared = ask(client, bob).json()
    assert shared["grounded"] is True
    assert shared["sources"][0]["filename"] == "notes.txt"

    client.delete(f"/shares/{share_id}", headers=alice)
    assert ask(client, bob).json()["grounded"] is False


def test_deleting_the_document_ends_shared_access(client, indexing):
    alice, bob, doc_id = alice_and_bob(client)
    share(client, alice, doc_id, "bob@example.com")
    assert len(search(client, bob)) == 1
    assert client.delete(f"/documents/{doc_id}", headers=alice).status_code == 204
    assert search(client, bob) == []


def test_grantee_still_searches_their_own_documents(client, indexing):
    alice, bob, doc_id = alice_and_bob(client)
    upload(client, bob, "bob.txt", OTHER)
    share(client, alice, doc_id, "bob@example.com")
    assert [hit["filename"] for hit in search(client, bob, OTHER.decode())] == ["bob.txt"]
    assert [hit["filename"] for hit in search(client, bob)] == ["notes.txt"]