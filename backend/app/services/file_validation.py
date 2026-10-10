import os
import re

_CANONICAL = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_EXTRA_DECLARED = {".md": {"text/x-markdown", "text/plain"}}
_NEUTRAL = {"", "application/octet-stream"}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class UploadValidationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def sanitize_filename(raw: str | None) -> str:
    """Display-only name. It is never used to build a filesystem path."""
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = _CONTROL_CHARS.sub("", name).strip().strip(".")
    if len(name) > 255:
        stem, ext = os.path.splitext(name)
        name = stem[: 255 - len(ext)] + ext
    return name or "unnamed"


def validate_upload(
    filename: str | None, content_type: str | None, data: bytes
) -> tuple[str, str, str]:
    """Return (clean_name, extension, canonical_mime) or raise UploadValidationError."""
    if not data:
        raise UploadValidationError("The file is empty")

    name = sanitize_filename(filename)
    extension = os.path.splitext(name)[1].lower()
    if extension not in _CANONICAL:
        allowed = ", ".join(sorted(_CANONICAL))
        raise UploadValidationError(f"Unsupported file type. Allowed: {allowed}", 415)

    declared = (content_type or "").split(";")[0].strip().lower()
    accepted = {_CANONICAL[extension]} | _EXTRA_DECLARED.get(extension, set()) | _NEUTRAL
    if declared not in accepted:
        raise UploadValidationError("The file type does not match its extension", 415)

    # The declared type comes from the client, so also check the real content.
    if extension == ".pdf" and not data.startswith(b"%PDF-"):
        raise UploadValidationError("The file content is not a valid PDF")
    if extension in (".docx", ".xlsx") and not data.startswith(b"PK\x03\x04"):
        raise UploadValidationError("The file content is not a valid Office document")

    return name, extension, _CANONICAL[extension]