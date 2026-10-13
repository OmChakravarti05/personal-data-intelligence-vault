from tests.test_auto_indexing import make_user, upload


def share(client, headers, document_id, email):
    return client.post("/shares", headers=headers, json={"document_id": document_id, "email": email})


def setup_shared(client):
    """Alice uploads a document and shares it with Bob. Returns (alice, bob, doc_id, share_id)."""
    alice = make_user(client, "alice@example.com")
    bob = make_user(client, "bob@example.com")
    doc_id = upload(client, alice).json()["id"]
    share_id = share(client, alice, doc_id, "bob@example.com").json()["id"]
    return alice, bob, doc_id, share_id


def test_sharing_requires_login(client):
    assert client.get("/shares/with-me").status_code == 401
    assert client.post("/shares", json={"document_id": "x", "email": "a@b.co"}).status_code in (401, 422)


def test_owner_shares_and_grantee_sees_it(client):
    alice, bob, doc_id, _ = setup_shared(client)
    shared = client.get("/shares/with-me", headers=bob).json()
    assert len(shared) == 1
    assert shared[0]["document_id"] == doc_id and shared[0]["filename"] == "notes.txt"
    assert shared[0]["shared_by_email"] == "alice@example.com"
    assert client.get("/shares/with-me", headers=alice).json() == []


def test_cannot_share_a_document_you_do_not_own(client):
    alice, bob, doc_id, _ = setup_shared(client)
    make_user(client, "carol@example.com")
    assert share(client, bob, doc_id, "carol@example.com").status_code == 404


def test_invalid_shares_are_rejected(client):
    alice = make_user(client, "alice@example.com")
    make_user(client, "bob@example.com")
    doc_id = upload(client, alice).json()["id"]
    assert share(client, alice, doc_id, "alice@example.com").status_code == 400
    assert share(client, alice, doc_id, "nobody@example.com").status_code == 404
    assert share(client, alice, doc_id, "bob@example.com").status_code == 201
    assert share(client, alice, doc_id, "bob@example.com").status_code == 409


def test_grantee_has_no_owner_only_powers(client):
    alice, bob, doc_id, _ = setup_shared(client)
    assert client.get(f"/documents/{doc_id}", headers=bob).status_code == 404
    assert client.get(f"/documents/{doc_id}/download", headers=bob).status_code == 404
    assert client.post(f"/documents/{doc_id}/reprocess", headers=bob).status_code == 404
    assert client.get("/pii/findings", headers=bob, params={"document_id": doc_id}).status_code == 404
    assert client.get(f"/pii/preview/{doc_id}", headers=bob).status_code == 404
    assert client.delete(f"/documents/{doc_id}", headers=bob).status_code == 404
    assert client.get("/documents", headers=bob).json()["total"] == 0
    # The owner's document is untouched.
    assert client.get(f"/documents/{doc_id}", headers=alice).status_code == 200


def test_owner_can_revoke(client):
    alice, bob, doc_id, share_id = setup_shared(client)
    assert client.delete(f"/shares/{share_id}", headers=alice).status_code == 204
    assert client.get("/shares/with-me", headers=bob).json() == []
    assert client.get(f"/shares/document/{doc_id}", headers=alice).json() == []


def test_grantee_can_leave_but_strangers_cannot_revoke(client):
    alice, bob, doc_id, share_id = setup_shared(client)
    carol = make_user(client, "carol@example.com")
    assert client.delete(f"/shares/{share_id}", headers=carol).status_code == 404
    assert client.delete(f"/shares/{share_id}", headers=bob).status_code == 204
    assert client.get("/shares/with-me", headers=bob).json() == []


def test_deleting_the_document_removes_its_shares(client):
    alice, bob, doc_id, _ = setup_shared(client)
    assert client.delete(f"/documents/{doc_id}", headers=alice).status_code == 204
    assert client.get("/shares/with-me", headers=bob).json() == []


def test_only_the_owner_can_list_who_has_access(client):
    alice, bob, doc_id, _ = setup_shared(client)
    carol = make_user(client, "carol@example.com")
    listing = client.get(f"/shares/document/{doc_id}", headers=alice).json()
    assert [item["grantee_email"] for item in listing] == ["bob@example.com"]
    assert listing[0]["permission"] == "read"
    assert client.get(f"/shares/document/{doc_id}", headers=bob).status_code == 404
    assert client.get(f"/shares/document/{doc_id}", headers=carol).status_code == 404


def test_grant_and_revoke_are_audited(client):
    alice, bob, doc_id, share_id = setup_shared(client)
    client.delete(f"/shares/{share_id}", headers=alice)
    events = client.get("/audit", headers=alice).json()["items"]
    by_type = {item["event_type"]: item for item in events}
    assert by_type["share.grant"]["resource_id"] == doc_id
    assert by_type["share.revoke"]["metadata"]["by"] == "owner"
    assert "bob@example.com" not in str(events)