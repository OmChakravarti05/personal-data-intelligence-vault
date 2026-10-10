import os
import re
import uuid
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.services.encryption import FileEncryptor

_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


class StorageError(Exception):
    pass


def new_storage_id() -> str:
    """Random identifier used on disk. User filenames never touch the filesystem."""
    return uuid.uuid4().hex


class StorageBackend(ABC):
    """Interface so encrypted object storage (S3, Azure) can replace local disk later."""

    @abstractmethod
    def save(self, storage_id: str, data: bytes) -> None: ...

    @abstractmethod
    def read(self, storage_id: str) -> bytes: ...

    @abstractmethod
    def delete(self, storage_id: str) -> None: ...

    @abstractmethod
    def exists(self, storage_id: str) -> bool: ...


class LocalEncryptedStorage(StorageBackend):
    def __init__(self, root: Path, encryptor: FileEncryptor) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._encryptor = encryptor

    def _path(self, storage_id: str) -> Path:
        if not _ID_PATTERN.fullmatch(storage_id):
            raise StorageError("Invalid storage id")
        path = (self._root / f"{storage_id}.bin").resolve()
        if path.parent != self._root:
            raise StorageError("Invalid storage path")
        return path

    def save(self, storage_id: str, data: bytes) -> None:
        path = self._path(storage_id)
        # The storage id is bound into the encryption, so a stored file
        # cannot be swapped for a different one without detection.
        blob = self._encryptor.encrypt(data, storage_id.encode())
        temp = path.with_suffix(".tmp")
        temp.write_bytes(blob)
        os.replace(temp, path)  # atomic: no half-written files

    def read(self, storage_id: str) -> bytes:
        path = self._path(storage_id)
        if not path.is_file():
            raise StorageError("File not found")
        return self._encryptor.decrypt(path.read_bytes(), storage_id.encode())

    def delete(self, storage_id: str) -> None:
        self._path(storage_id).unlink(missing_ok=True)

    def exists(self, storage_id: str) -> bool:
        return self._path(storage_id).is_file()


@lru_cache
def get_storage() -> StorageBackend:
    return LocalEncryptedStorage(
        settings.storage_dir, FileEncryptor(settings.encryption_key_bytes)
    )