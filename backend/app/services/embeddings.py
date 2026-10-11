from functools import lru_cache

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

from app.core.config import settings


class EmbeddingError(Exception):
    pass


class LocalEmbeddings(Embeddings):
    """Local Sentence Transformers model behind LangChain's Embeddings interface.

    Runs entirely on this machine, so document text is not sent to any external service.
    """

    def __init__(self, model_name: str, expected_dimension: int, batch_size: int = 32) -> None:
        self._model_name = model_name
        self._expected_dimension = expected_dimension
        self._batch_size = batch_size
        self._model: SentenceTransformer | None = None

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            try:
                model = SentenceTransformer(self._model_name)
            except Exception as exc:
                raise EmbeddingError(f"Could not load embedding model '{self._model_name}'") from exc
            # Newer versions renamed this method; support both.
            get_dimension = getattr(
                model, "get_embedding_dimension", None
            ) or model.get_sentence_embedding_dimension
            actual = get_dimension()
            if actual != self._expected_dimension:
                raise EmbeddingError(
                    f"Embedding model produces {actual}-dimensional vectors, but the "
                    f"database column expects {self._expected_dimension}"
                )
            self._model = model
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,  # unit length, so cosine distance is meaningful
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@lru_cache
def get_embeddings() -> LocalEmbeddings:
    return LocalEmbeddings(settings.embedding_model, settings.embedding_dimension)