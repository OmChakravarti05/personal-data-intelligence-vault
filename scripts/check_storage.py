import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.encryption import DecryptionError, FileEncryptor
from app.services.storage import LocalEncryptedStorage, StorageError, new_storage_id

with tempfile.TemporaryDirectory() as tmp:
    storage = LocalEncryptedStorage(Path(tmp), FileEncryptor(os.urandom(32)))
    sid = new_storage_id()
    secret = b"synthetic secret document text"

    storage.save(sid, secret)
    print("round trip works:", storage.read(sid) == secret)

    on_disk = (Path(tmp) / f"{sid}.bin").read_bytes()
    print("plaintext not on disk:", secret not in on_disk)

    (Path(tmp) / f"{sid}.bin").write_bytes(on_disk[:-1] + bytes([on_disk[-1] ^ 1]))
    try:
        storage.read(sid)
        print("tampering detected: False")
    except DecryptionError:
        print("tampering detected: True")

    try:
        storage.read("../../etc/passwd")
        print("path traversal blocked: False")
    except StorageError:
        print("path traversal blocked: True")

    storage.delete(sid)
    print("delete works:", not storage.exists(sid))