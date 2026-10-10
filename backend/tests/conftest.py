import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (registers all models)
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.encryption import FileEncryptor
from app.services.storage import LocalEncryptedStorage, get_storage

# Same server as development, but a separate database.
TEST_DB_URL = settings.database_url.rsplit("/", 1)[0] + "/vault_test"


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_tables(engine):
    """Empty every table before each test so tests never affect each other."""
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))


@pytest.fixture
def db_session(engine):
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def storage_dir(tmp_path):
    """Each test stores files in its own throwaway folder, never in ./storage."""
    return tmp_path / "storage"


@pytest.fixture
def client(engine, storage_dir):
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    test_storage = LocalEncryptedStorage(
        storage_dir, FileEncryptor(settings.encryption_key_bytes)
    )

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage] = lambda: test_storage
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()