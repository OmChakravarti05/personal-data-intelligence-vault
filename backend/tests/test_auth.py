from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select

from app.core.config import settings
from app.models import User

PASSWORD = "Correct-Horse-9"


def register(client, email="alice@example.com", password=PASSWORD):
    return client.post(
        "/auth/register",
        json={"email": email, "full_name": "Test Person", "password": password},
    )


def login(client, email="alice@example.com", password=PASSWORD):
    return client.post("/auth/login", data={"username": email, "password": password})


def auth_header(client, email="alice@example.com"):
    register(client, email)
    token = login(client, email).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_register_succeeds_and_hides_password(client):
    response = register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert "password" not in body and "hashed_password" not in body


def test_password_is_stored_hashed(client, db_session):
    register(client)
    user = db_session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user.hashed_password != PASSWORD
    assert user.hashed_password.startswith("$argon2id$")


def test_duplicate_email_is_rejected_case_insensitively(client):
    assert register(client, "alice@example.com").status_code == 201
    assert register(client, "ALICE@example.com").status_code == 409


def test_short_password_is_rejected(client):
    assert register(client, password="short").status_code == 422


def test_login_succeeds(client):
    register(client)
    response = login(client)
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_login_with_wrong_password_fails(client):
    register(client)
    assert login(client, password="Wrong-Password-1").status_code == 401


def test_login_with_unknown_email_gives_same_error(client):
    register(client)
    wrong_password = login(client, password="Wrong-Password-1")
    unknown_email = login(client, email="nobody@example.com")
    assert unknown_email.status_code == 401
    assert unknown_email.json() == wrong_password.json()


def test_me_requires_a_token(client):
    assert client.get("/auth/me").status_code == 401


def test_me_returns_the_current_user(client):
    response = client.get("/auth/me", headers=auth_header(client))
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


def test_me_rejects_a_tampered_token(client):
    headers = auth_header(client)
    headers["Authorization"] += "x"
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_me_rejects_an_expired_token(client, db_session):
    register(client)
    user = db_session.scalar(select(User).where(User.email == "alice@example.com"))
    expired = jwt.encode(
        {
            "sub": str(user.id),
            "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_each_user_only_sees_their_own_identity(client):
    alice = auth_header(client, "alice@example.com")
    bob = auth_header(client, "bob@example.com")
    assert client.get("/auth/me", headers=alice).json()["email"] == "alice@example.com"
    assert client.get("/auth/me", headers=bob).json()["email"] == "bob@example.com"


def test_deactivated_user_cannot_use_an_existing_token(client, db_session):
    headers = auth_header(client)
    user = db_session.scalar(select(User).where(User.email == "alice@example.com"))
    user.is_active = False
    db_session.commit()
    assert client.get("/auth/me", headers=headers).status_code == 401