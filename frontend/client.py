import os

import httpx

API_URL = os.environ.get("VAULT_API_URL", "http://127.0.0.1:8000")
# Short connect timeout, long read timeout: local model answers can take a while.
TIMEOUT = httpx.Timeout(10.0, read=200.0)


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return "Some values are not valid. Please check what you entered."
    return f"Request failed ({response.status_code})."


def request(method: str, path: str, token: str | None = None, **kwargs) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = httpx.request(
            method, f"{API_URL}{path}", headers=headers, timeout=TIMEOUT, **kwargs
        )
    except httpx.ConnectError:
        raise ApiError("Cannot reach the API. Is the backend running?")
    except httpx.TimeoutException:
        raise ApiError("The request timed out. Please try again.")
    if response.status_code >= 400:
        raise ApiError(_detail(response), response.status_code)
    return response


def login(email: str, password: str) -> str:
    response = request("POST", "/auth/login", data={"username": email, "password": password})
    return response.json()["access_token"]


def register(email: str, full_name: str, password: str) -> None:
    request(
        "POST",
        "/auth/register",
        json={"email": email, "full_name": full_name, "password": password},
    )


def me(token: str) -> dict:
    return request("GET", "/auth/me", token=token).json()


def get_stats(token: str) -> dict:
    return request("GET", "/stats", token=token).json()


def list_documents(
    token: str,
    q: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    params: dict = {"limit": limit, "offset": offset}
    if q:
        params["q"] = q
    if status:
        params["status"] = status
    return request("GET", "/documents", token=token, params=params).json()


def upload_document(token: str, filename: str, data: bytes, mime_type: str) -> dict:
    return request(
        "POST", "/documents/upload", token=token, files={"file": (filename, data, mime_type)}
    ).json()


def delete_document(token: str, document_id: str) -> None:
    request("DELETE", f"/documents/{document_id}", token=token)


def reprocess_document(token: str, document_id: str) -> dict:
    return request("POST", f"/documents/{document_id}/reprocess", token=token).json()


def pii_findings(token: str, document_id: str, limit: int = 100) -> dict:
    return request(
        "GET",
        "/pii/findings",
        token=token,
        params={"document_id": document_id, "limit": limit},
    ).json()


def pii_preview(token: str, document_id: str) -> dict:
    return request("GET", f"/pii/preview/{document_id}", token=token).json()


def ask(token: str, question: str, conversation_id: str | None = None) -> dict:
    body: dict = {"question": question}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return request("POST", "/chat/ask", token=token, json=body).json()


def list_conversations(token: str) -> list[dict]:
    return request("GET", "/chat/conversations", token=token).json()


def get_conversation(token: str, conversation_id: str) -> dict:
    return request("GET", f"/chat/conversations/{conversation_id}", token=token).json()


def delete_conversation(token: str, conversation_id: str) -> None:
    request("DELETE", f"/chat/conversations/{conversation_id}", token=token)