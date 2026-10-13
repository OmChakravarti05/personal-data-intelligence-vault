from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services.audit import audit, safe_metadata
from tests.test_auto_indexing import TEXT, indexing, make_user, upload  # noqa: F401
from tests.test_chat import ask, llm  # noqa: F401


def rows(engine):
    with Session(engine) as db:
        return list(db.scalars(select(AuditLog).order_by(AuditLog.created_at)))


def pairs(engine):
    return [(row.event_type, row.result) for row in rows(engine)]


class BrokenDb:
    def __init__(self):
        self.rolled_back = False

    def add(self, obj):
        raise RuntimeError("database is down")

    def commit(self):
        raise RuntimeError("database is down")

    def rollback(self):
        self.rolled_back = True


def test_safe_metadata_drops_secrets_and_truncates():
    result = safe_metadata(
        {
            "filename": "a.txt",
            "password": "x",
            "api_token": "y",
            "question_text": "hello",
            "size_bytes": 5,
            "nested": {"a": 1},
            "long": "z" * 500,
        }
    )
    assert result == {"filename": "a.txt", "size_bytes": 5, "long": "z" * 200}
    assert safe_metadata({}) is None and safe_metadata({"password": "x"}) is None


def test_audit_failure_never_breaks_the_caller():
    db = BrokenDb()
    audit(db, event_type="auth.login")  # must not raise
    assert db.rolled_back is True


def test_register_and_login_are_logged(client, engine):
    make_user(client)
    assert ("auth.register", "success") in pairs(engine)
    assert ("auth.login", "success") in pairs(engine)


def test_failed_login_is_logged_without_the_password(client, engine):
    headers = make_user(client)
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    response = client.post(
        "/auth/login", data={"username": "alice@example.com", "password": "Wrong-Password-1"}
    )
    assert response.status_code == 401
    failures = [row for row in rows(engine) if row.result == "failure"]
    assert len(failures) == 1
    assert str(failures[0].user_id) == user_id
    assert failures[0].event_metadata == {"reason": "bad_credentials"}


def test_failed_login_for_unknown_email_has_no_user(client, engine):
    response = client.post(
        "/auth/login", data={"username": "nobody@example.com", "password": "Wrong-Password-1"}
    )
    assert response.status_code == 401
    failures = [row for row in rows(engine) if row.result == "failure"]
    assert len(failures) == 1 and failures[0].user_id is None
    assert "nobody" not in str(failures[0].event_metadata)


def test_upload_download_delete_are_logged(client, engine):
    headers = make_user(client)
    doc_id = upload(client, headers).json()["id"]
    assert client.get(f"/documents/{doc_id}/download", headers=headers).status_code == 200
    assert client.delete(f"/documents/{doc_id}", headers=headers).status_code == 204

    events = {row.event_type: row for row in rows(engine) if row.event_type.startswith("document.")}
    assert set(events) == {"document.upload", "document.download", "document.delete"}
    assert all(row.resource_id == doc_id for row in events.values())
    assert events["document.upload"].event_metadata["filename"] == "notes.txt"
    assert events["document.upload"].event_metadata["size_bytes"] == len(TEXT.encode())


def test_rejected_upload_is_logged_as_failure(client, engine):
    headers = make_user(client)
    response = upload(client, headers, "program.exe", b"MZ fake binary", "application/x-msdownload")
    assert response.status_code >= 400
    failures = [row for row in rows(engine) if row.event_type == "document.upload"]
    assert len(failures) == 1 and failures[0].result == "failure"
    assert failures[0].event_metadata["reason"]


def test_chat_ask_is_logged_without_the_question(client, indexing, llm, engine):
    headers = make_user(client)
    upload(client, headers)
    ask(client, headers)
    events = [row for row in rows(engine) if row.event_type == "chat.ask"]
    assert len(events) == 1 and events[0].result == "success"
    assert events[0].event_metadata["grounded"] is True
    assert "budget" not in str(events[0].event_metadata)