import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.llm import get_llm

try:
    print(get_llm().invoke("Reply with exactly: ready").content)
except Exception as exc:
    print(type(exc).__name__, "-", exc)