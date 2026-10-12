import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import User
from app.services.embeddings import get_embeddings
from app.services.llm import get_llm
from app.services.rag import answer_question

if len(sys.argv) < 3:
    sys.exit('Usage: python scripts\\check_rag.py <email> "question"')

email, question = sys.argv[1], sys.argv[2]
with SessionLocal() as db:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        sys.exit("No such user.")
    result = answer_question(db, user.id, get_embeddings(), get_llm(), question)

print("grounded:", result.grounded)
print("answer  :", result.answer)
for source in result.sources:
    print(f"  [{source.number}] {source.hit.filename} distance={source.hit.distance:.4f} cited={source.cited}")