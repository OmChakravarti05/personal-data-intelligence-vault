import uuid

import pymupdf
from sqlalchemy import func, select

from app.models import PIIFinding
from app.services.pii_detection import detect_pii, redact_text

EMAIL = "priya.sharma@example.com"
PHONE = "+91 98765 43210"
CARD = "4111 1111 1111 1111"
PAN = "ABCDE1234F"
AADHAAR = "2345 6789 0123"

SAMPLE = (
    f"Contact: {EMAIL}\nMobile: {PHONE}\nCard: {CARD}\n"
    "The budget review is on Monday.\n"
)
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


def upload(client, headers, name="notes.txt", data=SAMPLE.encode(), ctype="text/plain"):
    return client.post(
        "/documents/upload", headers=headers, files={"file": (name, data, ctype)}
    )


def uploaded_and_scanned(client, headers):
    doc_id = upload(client, headers).json()["id"]
    assert client.post(f"/pii/scan/{doc_id}", headers=headers).status_code == 200
    return doc_id


# ---- Detection and redaction (no database needed) ----

def test_detects_common_categories():
    found = {m.category for m in detect_pii(SAMPLE)}
    assert {"EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"} <= found


def test_detects_indian_ids():
    found = {m.category for m in detect_pii(f"PAN: {PAN}\nAadhaar: {AADHAAR}\n")}
    assert {"PAN_NUMBER", "AADHAAR_NUMBER"} <= found


def test_matches_hold_no_raw_values():
    matches = detect_pii(SAMPLE)
    assert matches
    for match in matches:
        assert EMAIL not in repr(match) and CARD not in repr(match)


def test_empty_text_has_no_matches():
    assert detect_pii("   ") == []


def test_category_filter():
    matches = detect_pii(SAMPLE, categories=("EMAIL_ADDRESS",))
    assert matches and {m.category for m in matches} == {"EMAIL_ADDRESS"}


def test_redaction_removes_values_and_keeps_text():
    redacted = redact_text(SAMPLE, detect_pii(SAMPLE))
    for value in (EMAIL, PHONE, CARD):
        assert value not in redacted
    assert "[EMAIL_ADDRESS]" in redacted
    assert "budget review is on Monday" in redacted


def test_offsets_point_at_the_value():
    email_match = next(m for m in detect_pii(SAMPLE) if m.category == "EMAIL_ADDRESS")
    assert SAMPLE[email_match.start : email_match.end] == EMAIL


# ---- API ----

def test_scan_stores_findings_without_values(client):
    headers = make_user(client)
    doc_id = upload(client, headers).json()["id"]
    scan = client.post(f"/pii/scan/{doc_id}", headers=headers)
    assert scan.status_code == 200
    assert {"EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"} <= set(scan.json()["by_category"])
    assert "disclaimer" in scan.json()

    listing = client.get("/pii/findings", headers=headers, params={"document_id": doc_id})
    assert listing.status_code == 200 and listing.json()["total"] >= 3
    assert EMAIL not in listing.text and CARD not in listing.text


def test_rescan_does_not_duplicate_findings(client):
    headers = make_user(client)
    doc_id = upload(client, headers).json()["id"]
    first = client.post(f"/pii/scan/{doc_id}", headers=headers).json()["total_findings"]
    second = client.post(f"/pii/scan/{doc_id}", headers=headers).json()["total_findings"]
    stored = client.get(
        "/pii/findings", headers=headers, params={"document_id": doc_id}
    ).json()["total"]
    assert first == second == stored


def test_preview_is_redacted(client):
    headers = make_user(client)
    doc_id = upload(client, headers).json()["id"]
    response = client.get(f"/pii/preview/{doc_id}", headers=headers)
    assert response.status_code == 200
    text = response.json()["segments"][0]["text"]
    assert "[EMAIL_ADDRESS]" in text and "budget review is on Monday" in text
    for value in (EMAIL, PHONE, CARD):
        assert value not in response.text


def test_preview_truncates_long_documents(client):
    headers = make_user(client)
    body = f"Contact: {EMAIL}\n" + "Routine status update line for the quarterly review.\n" * 600
    doc_id = upload(client, headers, data=body.encode()).json()["id"]
    response = client.get(f"/pii/preview/{doc_id}", headers=headers).json()
    text = response["segments"][0]["text"]
    assert response["truncated"] is True
    assert len(text) <= 20_000
    assert EMAIL not in text and "[EMAIL_ADDRESS]" in text


def test_pdf_findings_keep_page_numbers(client):
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Quarterly summary page one")
    pdf.new_page().insert_text((72, 72), f"Reach me at {EMAIL}")
    headers = make_user(client)
    doc_id = upload(client, headers, "report.pdf", pdf.tobytes(), "application/pdf").json()["id"]
    assert client.post(f"/pii/scan/{doc_id}", headers=headers).status_code == 200
    items = client.get(
        "/pii/findings", headers=headers, params={"document_id": doc_id}
    ).json()["items"]
    email_findings = [i for i in items if i["category"] == "EMAIL_ADDRESS"]
    assert email_findings and email_findings[0]["page_number"] == 2


def test_failed_document_cannot_be_scanned(client):
    headers = make_user(client)
    doc = upload(client, headers, "bad.docx", b"PK\x03\x04garbage", DOCX_MIME).json()
    assert doc["status"] == "failed"
    assert client.post(f"/pii/scan/{doc['id']}", headers=headers).status_code == 409
    assert client.get(f"/pii/preview/{doc['id']}", headers=headers).status_code == 409


def test_pii_endpoints_require_login(client):
    some_id = uuid.uuid4()
    assert client.get("/pii/findings").status_code == 401
    assert client.get(f"/pii/findings/{some_id}").status_code == 401
    assert client.post(f"/pii/scan/{some_id}").status_code == 401
    assert client.get(f"/pii/preview/{some_id}").status_code == 401


def test_findings_filter_by_category(client):
    headers = make_user(client)
    uploaded_and_scanned(client, headers)
    response = client.get("/pii/findings", headers=headers, params={"category": "email_address"})
    body = response.json()
    assert response.status_code == 200 and body["total"] == 1
    assert all(i["category"] == "EMAIL_ADDRESS" for i in body["items"])


# ---- Cross-user isolation ----

def test_cross_user_scan_is_404(client):
    alice, bob = make_user(client, "alice@example.com"), make_user(client, "bob@example.com")
    doc_id = upload(client, alice).json()["id"]
    assert client.post(f"/pii/scan/{doc_id}", headers=bob).status_code == 404


def test_cross_user_preview_is_404(client):
    alice, bob = make_user(client, "alice@example.com"), make_user(client, "bob@example.com")
    doc_id = upload(client, alice).json()["id"]
    assert client.get(f"/pii/preview/{doc_id}", headers=bob).status_code == 404


def test_cross_user_findings_filter_by_foreign_document_is_404(client):
    alice, bob = make_user(client, "alice@example.com"), make_user(client, "bob@example.com")
    doc_id = uploaded_and_scanned(client, alice)
    response = client.get("/pii/findings", headers=bob, params={"document_id": doc_id})
    assert response.status_code == 404


def test_cross_user_cannot_see_or_fetch_findings(client):
    alice, bob = make_user(client, "alice@example.com"), make_user(client, "bob@example.com")
    doc_id = uploaded_and_scanned(client, alice)
    finding_id = client.get(
        "/pii/findings", headers=alice, params={"document_id": doc_id}
    ).json()["items"][0]["id"]
    assert client.get("/pii/findings", headers=bob).json()["total"] == 0
    assert client.get(f"/pii/findings/{finding_id}", headers=bob).status_code == 404
    assert client.get(f"/pii/findings/{finding_id}", headers=alice).status_code == 200


def test_unknown_and_invalid_ids(client):
    headers = make_user(client)
    assert client.get(f"/pii/findings/{uuid.uuid4()}", headers=headers).status_code == 404
    assert client.post(f"/pii/scan/{uuid.uuid4()}", headers=headers).status_code == 404
    assert client.get("/pii/findings/not-a-uuid", headers=headers).status_code == 422


def test_deleting_a_document_removes_its_findings(client, db_session):
    headers = make_user(client)
    doc_id = uploaded_and_scanned(client, headers)
    count = lambda: db_session.scalar(select(func.count()).select_from(PIIFinding))
    assert count() >= 3
    assert client.delete(f"/documents/{doc_id}", headers=headers).status_code == 204
    db_session.expire_all()
    assert count() == 0