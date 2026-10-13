from app.core.config import settings

CREDS = {"email": "info.user@example.com", "full_name": "Info User", "password": "Correct-Horse-9"}


def auth_headers(client):
    client.post("/auth/register", json=CREDS)
    token = client.post(
        "/auth/login", data={"username": CREDS["email"], "password": CREDS["password"]}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_system_info_requires_login(client):
    assert client.get("/system/info").status_code == 401


def test_system_info_local_by_default(client):
    body = client.get("/system/info", headers=auth_headers(client)).json()
    assert body["llm_provider"] == "ollama"
    assert body["external_llm"] is False
    assert body["llm_model"] == settings.llm_model


def test_system_info_reports_groq_and_never_leaks_key(client, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", SecretStr("test-key-not-real"))
    response = client.get("/system/info", headers=auth_headers(client))
    assert response.json()["external_llm"] is True
    assert "test-key-not-real" not in response.text