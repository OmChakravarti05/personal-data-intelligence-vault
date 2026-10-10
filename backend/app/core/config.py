import base64
import binascii
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] is the project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_port: int = 5433
    postgres_host: str = "127.0.0.1"

    # Authentication
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # File storage and encryption
    encryption_key: str
    max_upload_mb: int = 20
    storage_dir: Path = PROJECT_ROOT / "storage"

    @field_validator("jwt_secret_key")
    @classmethod
    def secret_must_be_long_enough(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        return value

    @field_validator("encryption_key")
    @classmethod
    def key_must_be_32_bytes(cls, value: str) -> str:
        try:
            raw = base64.urlsafe_b64decode(value.encode())
        except (binascii.Error, ValueError) as exc:
            raise ValueError("ENCRYPTION_KEY must be url-safe base64") from exc
        if len(raw) != 32:
            raise ValueError("ENCRYPTION_KEY must decode to exactly 32 bytes")
        return value

    @property
    def encryption_key_bytes(self) -> bytes:
        return base64.urlsafe_b64decode(self.encryption_key.encode())

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def database_url(self) -> str:
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+psycopg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()