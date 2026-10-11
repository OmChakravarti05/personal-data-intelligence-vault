import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.chunking import chunk_segments
from app.services.embeddings import get_embeddings

# ---- Chunking ----
sentences = [f"Sentence number {i} is about the quarterly budget." for i in range(120)]
text = " ".join(sentences)
chunks = chunk_segments([(None, text)], chunk_size=500, chunk_overlap=100)
print("produces several chunks:", len(chunks) > 3)
print("chunks respect the size limit:", all(len(c.content) <= 500 for c in chunks))
print("chunk indexes are sequential:", [c.chunk_index for c in chunks] == list(range(len(chunks))))
print("no sentence is lost:", all(any(s in c.content for c in chunks) for s in sentences))

paged = chunk_segments(
    [(1, "Page one text. " * 80), (2, "Page two text. " * 80)],
    chunk_size=300,
    chunk_overlap=50,
)
print("page numbers kept:", {c.page_number for c in paged} == {1, 2})
print("chunks never span pages:", all(("one" in c.content) != ("two" in c.content) for c in paged))
print("empty input gives no chunks:", chunk_segments([(None, "   ")]) == [])

# ---- Embeddings (first run downloads the model, about 90 MB) ----
embedder = get_embeddings()
vectors = embedder.embed_documents(
    [
        "The invoice total for March was paid by bank transfer.",
        "Payment for the March bill was made through a wire transfer.",
        "Mountain trails are best hiked during early autumn.",
    ]
)
print("vector dimension is 384:", all(len(v) == 384 for v in vectors))
print("vectors are unit length:", all(abs(math.sqrt(sum(x * x for x in v)) - 1) < 1e-3 for v in vectors))


def similarity(a, b):
    return sum(x * y for x, y in zip(a, b))


print(
    "related text is closer than unrelated:",
    similarity(vectors[0], vectors[1]) > similarity(vectors[0], vectors[2]),
)
print("query embedding matches dimension:", len(embedder.embed_query("March payment")) == 384)
print("empty list gives empty result:", embedder.embed_documents([]) == [])