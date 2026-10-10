import uuid

from app.core.config import settings

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def make_user(client, email="alice@example.com"):
    client.post(
        "/auth/register",
        json={"email": email, "full_name": "Test Person", "password": "Correct-Horse-9"},
    )
    token = client.post(
        "/auth/login", data={"username": email, "password": "Correct-Horse-9"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def upload(client, headers, name="notes.txt", data=b"Synthetic meeting notes", ctype="text/plain"):
    return client.post(
        "/documents/upload", headers=headers, files={"file": (name, data, ctype)}
    )


def stored_files(storage_dir):
    return list(storage_dir.glob("*.bin"))


def test_upload_succeeds_and_hides_internal_fields(client):
    response = upload(client, make_user(client))
    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "notes.txt"
    assert body["status"] == "uploaded"
    for hidden in ("storage_id", "file_hash", "owner_id"):
        assert hidden not in body


def test_stored_file_is_encrypted(client, storage_dir):
    upload(client, make_user(client), data=b"Synthetic secret budget text")
    files = stored_files(storage_dir)
    assert len(files) == 1
    assert b"secret budget" not in files[0].read_bytes()


def test_duplicate_upload_rejected(client):
    headers = make_user(client)
    assert upload(client, headers).status_code == 201
    assert upload(client, headers).status_code == 409


def test_unsupported_extension_rejected(client):
    response = upload(client, make_user(client), "run.exe", b"data", "application/octet-stream")
    assert response.status_code == 415


def test_mismatched_content_type_rejected(client):
    response = upload(client, make_user(client), "notes.txt", b"hello", "image/png")
    assert response.status_code == 415


def test_fake_pdf_rejected(client):
    response = upload(client, make_user(client), "fake.pdf", b"not a pdf", "application/pdf")
    assert response.status_code == 400


def test_empty_file_rejected(client):
    assert upload(client, make_user(client), data=b"").status_code == 400


def test_oversized_file_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    response = upload(client, make_user(client), data=b"a" * (2 * 1024 * 1024))
    assert response.status_code == 413


def test_corrupt_docx_is_marked_failed(client):
    response = upload(client, make_user(client), "bad.docx", b"PK\x03\x04garbage", DOCX_MIME)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"]


def test_filename_path_traversal_is_neutralised(client, storage_dir):
    response = upload(client, make_user(client), "../../evil.txt")
    assert response.status_code == 201
    assert response.json()["original_filename"] == "evil.txt"
    assert not (storage_dir.parent / "evil.txt").exists()
    assert all(f.suffix == ".bin" for f in storage_dir.iterdir())


def test_endpoints_require_login(client):
    some_id = uuid.uuid4()
    assert client.get("/documents").status_code == 401
    assert client.post("/documents/upload").status_code == 401
    assert client.get(f"/documents/{some_id}").status_code == 401
    assert client.get(f"/documents/{some_id}/download").status_code == 401
    assert client.delete(f"/documents/{some_id}").status_code == 401
    assert client.post(f"/documents/{some_id}/reprocess").status_code == 401


def test_list_shows_only_own_documents(client):
    alice, bob = make_user(client, "alice@example.com"), make_user(client, "bob@example.com")
    upload(client, alice, "alice.txt", b"alice private text")
    upload(client, bob, "bob.txt", b"bob private text")
    alice_list = client.get("/documents", headers=alice).json()
    assert alice_list["total"] == 1
    assert alice_list["items"][0]["original_filename"] == "alice.txt"


def test_list_search_and_pagination(client):
    headers = make_user(client)
    upload(client, headers, "budget.txt", b"one")
    upload(client, headers, "plan.txt", b"two")
    upload(client, headers, "notes.txt", b"three")
    search = client.get("/documents", headers=headers, params={"q": "budget"}).json()
    assert search["total"] == 1
    page1 = client.get("/documents", headers=headers, params={"limit": 2}).json()
    page2 = client.get("/documents", headers=headers, params={"limit": 2, "offset": 2}).json()
    assert page1["total"] == 3 and len(page1["items"]) == 2 and len(page2["items"]) == 1


def test_download_returns_original_bytes(client):
    headers = make_user(client)
    doc_id = upload(client, headers, data=b"Synthetic meeting notes").json()["id"]
    response = client.get(f"/documents/{doc_id}/download", headers=headers)
    assert response.status_code == 200
    assert response.content == b"Synthetic meeting notes"
    assert "attachment" in response.headers["content-disposition"]


def test_delete_removes_record_and_file(client, storage_dir):
    headers = make_user(client)
    doc_id = upload(client, headers).json()["id"]
    assert len(stored_files(storage_dir)) == 1
    assert client.delete(f"/documents/{doc_id}", headers=headers).status_code == 204
    assert client.get(f"/documents/{doc_id}", headers=headers).status_code == 404
    assert stored_files(storage_dir) == []


# ---- Cross-user isolation: the most important tests in the project ----

def test_cross_user_get_is_404(client):
    alice, bob = make_user(client, "alice@example.com"), make_user(client, "bob@example.com")
    doc_id = upload(client, alice).json()["id"]
    assert client.get(f"/documents/{doc_id}", headers=bob).status_code == 404


def test_cross_user_download_is_404(client):
    alice, bob = make_user(client, "alice@example.com"), make_user(client, "bob@example.com")
    doc_id = upload(client, alice).json()["id"]
    assert client.get(f"/documents/{doc_id}/download", headers=bob).status_code == 404


def test_cross_user_delete_is_404_and_keeps_file(client, storage_dir):
    alice, bob = make_user(client, "alice@example.com"), make_user(client, "bob@example.com")
    doc_id = upload(client, alice).json()["id"]
    assert client.delete(f"/documents/{doc_id}", headers=bob).status_code == 404
    assert client.get(f"/documents/{doc_id}", headers=alice).status_code == 200
    assert len(stored_files(storage_dir)) == 1


def test_cross_user_reprocess_is_404(client):
    alice, bob = make_user(client, "alice@example.com"), make_user(client, "bob@example.com")
    doc_id = upload(client, alice).json()["id"]
    assert client.post(f"/documents/{doc_id}/reprocess", headers=bob).status_code == 404


def test_unknown_and_invalid_ids(client):
    headers = make_user(client)
    assert client.get(f"/documents/{uuid.uuid4()}", headers=headers).status_code == 404
    assert client.get("/documents/not-a-uuid", headers=headers).status_code == 422


def test_reprocess_keeps_valid_document_uploaded(client):
    headers = make_user(client)
    doc_id = upload(client, headers).json()["id"]
    response = client.post(f"/documents/{doc_id}/reprocess", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "uploaded"