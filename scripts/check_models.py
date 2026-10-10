import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app.models  # noqa: F401  (registers the models)
from app.db.base import Base
from sqlalchemy.orm import configure_mappers

configure_mappers()
print(sorted(Base.metadata.tables))