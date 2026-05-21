"""
RAG retrieval function for PlayDesk.

retrieve(query, k, lang, category) embeds the query with the injected embedding
client and performs a pgvector cosine-similarity search over KnowledgeChunk.

The embedding client is injectable:
    from rag import embeddings, retriever
    embeddings.set_embedding_client(FakeEmbeddingClient())
    results = retriever.retrieve("Can I bring food?")
"""

from __future__ import annotations

from django.conf import settings
from pgvector.django import CosineDistance

from core.models import KnowledgeChunk

from .embeddings import get_embedding_client


def retrieve(
    query: str,
    k: int | None = None,
    lang: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """
    Retrieve the top-k most relevant KnowledgeChunks for *query*.

    Parameters
    ----------
    query:
        Natural-language query string.
    k:
        Number of results to return (default: RAG_TOP_K from settings, i.e. 5).
    lang:
        Optional ISO-639-1 language filter (e.g. "en", "zh").
    category:
        Optional category filter (e.g. "policies", "faq").

    Returns
    -------
    List of dicts, each containing:
        chunk_id, content, category, source, lang, score
    where *score* is a cosine **similarity** in [0, 1].
    """
    if k is None:
        k = settings.RAG_TOP_K

    client = get_embedding_client()
    query_vector = client.embed(query)

    qs = KnowledgeChunk.objects.annotate(distance=CosineDistance("embedding", query_vector))

    if lang is not None:
        qs = qs.filter(lang=lang)
    if category is not None:
        qs = qs.filter(category=category)

    qs = qs.order_by("distance")[:k]

    results = []
    for chunk in qs:
        # CosineDistance returns distance ∈ [0, 2]; similarity = 1 - distance
        similarity = max(0.0, min(1.0, 1.0 - float(chunk.distance)))
        results.append(
            {
                "chunk_id": chunk.pk,
                "content": chunk.content,
                "category": chunk.category,
                "source": chunk.source,
                "lang": chunk.lang,
                "score": similarity,
            }
        )

    return results
