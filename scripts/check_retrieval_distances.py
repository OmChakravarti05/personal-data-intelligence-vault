import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.embeddings import get_embeddings

texts = {
    "finance": "The electricity bill for March was 4,200 rupees and was paid on the 5th.",
    "hiking": "The best hiking trail in autumn is the ridge route with views of the valley.",
    "cooking": "Mix the flour and eggs, then rest the pasta dough for thirty minutes.",
}
queries = [
    "How much was the electricity bill?",
    "Which trail should I hike in autumn?",
    "What is the capital of France?",
    "Who won the cricket world cup?",
]

embedder = get_embeddings()
doc_vectors = dict(zip(texts, embedder.embed_documents(list(texts.values()))))

print(f"{'query':40} " + " ".join(f"{name:>8}" for name in texts))
for query in queries:
    q = embedder.embed_query(query)
    row = [1 - sum(a * b for a, b in zip(q, v)) for v in doc_vectors.values()]
    print(f"{query:40} " + " ".join(f"{d:8.3f}" for d in row))