import sys
from pathlib import Path

# Make the backend package importable when run from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text

from app.db.session import engine

with engine.connect() as conn:
    print(conn.execute(text("SELECT version()")).scalar())
    print(
        "pgvector:",
        conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar(),
    )