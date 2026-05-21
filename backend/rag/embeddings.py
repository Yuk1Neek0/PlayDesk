"""
Embedding client interface for PlayDesk RAG layer.

The real implementation calls OpenAI text-embedding-3-small.
Tests inject a FakeEmbeddingClient to avoid API calls in CI.

Usage:
    from rag.embeddings import get_embedding_client
    client = get_embedding_client()
    vector = client.embed("some text")
"""

from __future__ import annotations

import abc

from django.conf import settings


class EmbeddingClient(abc.ABC):
    """Abstract interface for embedding providers."""

    @abc.abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return an embedding vector for a single text string."""

    @abc.abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a list of text strings (one per input)."""


class OpenAIEmbeddingClient(EmbeddingClient):
    """Production client: calls OpenAI text-embedding-3-small (or the model in settings)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        import openai  # import lazily so tests that mock the interface don't need openai installed

        self._client = openai.OpenAI(api_key=api_key or settings.OPENAI_API_KEY)
        self._model = model or settings.EMBEDDING_MODEL
        self._dimensions = dimensions or settings.EMBEDDING_DIMENSIONS

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings.create(
            input=[text],
            model=self._model,
            dimensions=self._dimensions,
        )
        return response.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(
            input=texts,
            model=self._model,
            dimensions=self._dimensions,
        )
        # API returns results in the same order as input
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


class FakeEmbeddingClient(EmbeddingClient):
    """
    Deterministic fake for tests and CI.

    Returns a unit vector of the configured dimensions with a small hash-based
    perturbation so different texts produce different (but reproducible) vectors.
    No API calls are made.
    """

    def __init__(self, dimensions: int | None = None) -> None:
        self._dimensions = dimensions or settings.EMBEDDING_DIMENSIONS

    def embed(self, text: str) -> list[float]:
        import hashlib
        import math

        # Derive a seed from the text hash; normalise to a unit sphere.
        digest = int(hashlib.md5(text.encode()).hexdigest(), 16)  # noqa: S324
        vec = [(((digest >> i) & 0xFF) / 255.0) for i in range(self._dimensions)]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


# ---------------------------------------------------------------------------
# Module-level factory
# ---------------------------------------------------------------------------
_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    """
    Return the singleton embedding client.

    During normal operation this is an OpenAIEmbeddingClient.
    Tests override this by calling set_embedding_client() with a FakeEmbeddingClient.
    """
    global _client
    if _client is None:
        _client = OpenAIEmbeddingClient()
    return _client


def set_embedding_client(client: EmbeddingClient) -> None:
    """Replace the module-level client (used in tests)."""
    global _client
    _client = client


def reset_embedding_client() -> None:
    """Reset to None so the next call to get_embedding_client() creates a fresh instance."""
    global _client
    _client = None
