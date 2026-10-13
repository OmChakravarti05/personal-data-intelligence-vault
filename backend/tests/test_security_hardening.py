import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import settings
from app.core.security import decode_access_token
from app.services.file_validation import (
    UploadValidationError,
    sanitize_filename,
    validate_upload,
)

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ---------- JWT validation ----------

def make_token(**overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "type": "access",
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    secret = overrides.pop("_secret", settings.jwt_secret_key)
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm), payload


def test_valid_token_returns_user_id():
    token, payload = make_token()
    assert decode_access_token(token) == uuid.UUID(payload["sub"])


def test_expired_token_is_rejected():
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    token, _ = make_token(exp=past)
    assert decode_access_token(token) is None


def test_token_signed_with_wrong_secret_is_rejected():
    payload = {
        "sub": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "type": "access",
    }
    token = jwt.encode(payload, "not-the-real-secret-not-the-real-secret", algorithm="HS256")
    assert decode_access_token(token) is None


def test_token_of_wrong_type_is_rejected():
    token, _ = make_token(type="refresh")
    assert decode_access_token(token) is None


def test_token_without_expiry_is_rejected():
    payload = {"sub": str(uuid.uuid4()), "type": "access"}
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    assert decode_access_token(token) is None


def test_token_without_subject_is_rejected():
    payload = {
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "type": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    assert decode_access_token(token) is None


def test_token_with_non_uuid_subject_is_rejected():
    token, _ = make_token(sub="not-a-uuid")
    assert decode_access_token(token) is None


def test_unsigned_alg_none_token_is_rejected():
    payload = {
        "sub": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        "type": "access",
    }
    token = jwt.encode(payload, "", algorithm="none")
    assert decode_access_token(token) is None


@pytest.mark.parametrize("junk", ["", "abc", "a.b.c", "Bearer xyz"])
def test_garbage_tokens_are_rejected(junk):
    assert decode_access_token(junk) is None


# ---------- upload validation ----------

def test_empty_file_is_rejected():
    with pytest.raises(UploadValidationError):
        validate_upload("a.pdf", "application/pdf", b"")


def test_unsupported_extension_is_rejected_with_415():
    with pytest.raises(UploadValidationError) as err:
        validate_upload("virus.exe", "application/octet-stream", b"MZ data")
    assert err.value.status_code == 415


def test_declared_type_must_match_extension():
    with pytest.raises(UploadValidationError) as err:
        validate_upload("a.pdf", "image/png", b"%PDF-1.7 data")
    assert err.value.status_code == 415


def test_fake_pdf_content_is_rejected():
    with pytest.raises(UploadValidationError):
        validate_upload("a.pdf", "application/pdf", b"this is not a pdf")


def test_fake_docx_content_is_rejected():
    with pytest.raises(UploadValidationError):
        validate_upload("a.docx", DOCX, b"plain text pretending to be docx")


def test_valid_pdf_returns_name_extension_and_mime():
    name, ext, mime = validate_upload("report.PDF", "application/pdf", b"%PDF-1.7 body")
    assert (name, ext, mime) == ("report.PDF", ".pdf", "application/pdf")


def test_valid_docx_signature_is_accepted():
    name, ext, mime = validate_upload("memo.docx", DOCX, b"PK\x03\x04 rest")
    assert ext == ".docx" and mime == DOCX


# ---------- filename sanitising ----------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32\\evil.txt", "evil.txt"),
        ("C:\\Users\\me\\notes.txt", "notes.txt"),
        ("na\x00me\x07.txt", "name.txt"),
        ("   ", "unnamed"),
        ("...", "unnamed"),
        (None, "unnamed"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_very_long_filename_is_truncated_but_keeps_extension():
    name = sanitize_filename("a" * 400 + ".pdf")
    assert len(name) == 255
    assert name.endswith(".pdf")