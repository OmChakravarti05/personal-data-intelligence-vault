import hashlib
import math

from langchain_core.embeddings import Embeddings

from app.services.embeddings import EmbeddingError


class FakeEmbeddings(Embeddings):
    """Deterministic 384-dimensional vectors, with no model download.

    The same text always gives the same vector, so an exact-text query is an
    exact match. Different texts give unrelated vectors.
    """

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.query_calls = 0

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        raw = [(digest[i % 32] + i) % 17 - 8 for i in range(384)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]

    def embed_documents(self, texts):
        self.calls += 1
        if self.fail:
            raise EmbeddingError("simulated failure")
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        self.query_calls += 1
        return self._vector(text)