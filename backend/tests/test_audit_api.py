from tests.test_auto_indexing import make_user, upload


def get(client, headers, **params):
    response = client.get("/audit", headers=headers, params=params)
    assert response.status_code == 200
    return response.json()


def test_audit_requires_login(client):
    assert client.get("/audit").status_code == 401


def test_events_are_returned_newest_first(client):
    headers = make_user(client)
    body = get(client, headers)
    assert body["total"] == 2
    assert [item["event_type"] for item in body["items"]] == ["auth.login", "auth.register"]


def test_users_only_see_their_own_events(client):
    alice = make_user(client, "alice@example.com")
    bob = make_user(client, "bob@example.com")
    upload(client, alice)
    alice_types = {item["event_type"] for item in get(client, alice)["items"]}
    bob_body = get(client, bob)
    assert "document.upload" in alice_types
    assert "document.upload" not in {item["event_type"] for item in bob_body["items"]}
    assert bob_body["total"] == 2


def test_filters_by_event_type_and_result(client):
    headers = make_user(client)
    upload(client, headers)
    upload(client, headers)  # same file again: rejected as a duplicate

    uploads = get(client, headers, event_type="document.upload")
    assert uploads["total"] == 2

    failures = get(client, headers, result="failure")
    assert [item["event_type"] for item in failures["items"]] == ["document.upload"]
    assert failures["items"][0]["metadata"] == {"reason": "duplicate"}


def test_pagination(client):
    headers = make_user(client)
    first = get(client, headers, limit=1)
    second = get(client, headers, limit=1, offset=1)
    assert first["total"] == 2 and len(first["items"]) == 1
    assert first["items"][0]["event_type"] == "auth.login"
    assert second["items"][0]["event_type"] == "auth.register"


def test_failed_login_for_unknown_email_is_not_shown_to_anyone(client):
    headers = make_user(client)
    client.post("/auth/login", data={"username": "nobody@example.com", "password": "Wrong-Password-1"})
    assert get(client, headers, result="failure")["total"] == 0


def test_response_has_no_internal_fields(client):
    headers = make_user(client)
    item = get(client, headers)["items"][0]
    assert set(item) == {
        "id",
        "event_type",
        "resource_type",
        "resource_id",
        "result",
        "metadata",
        "created_at",
    }


def test_invalid_result_filter_is_rejected(client):
    headers = make_user(client)
    assert client.get("/audit", headers=headers, params={"result": "maybe"}).status_code == 422