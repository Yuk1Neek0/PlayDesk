"""
Migration 0003: Add HNSW index to KnowledgeChunk.embedding for cosine similarity search.

Uses pgvector HnswIndex (requires pgvector >= 0.5.0).

IVFFlat fallback: if your pgvector version does not support HNSW, replace the
index class with IVFFlat:

    from pgvector.django import IVFFlat
    IVFFlat(
        name="knowledge_chunk_embedding_ivfflat",
        fields=["embedding"],
        opclasses=["vector_cosine_ops"],
        lists=100,    # tune to approx sqrt(total_rows)
    )
"""

import pgvector.django
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_initial_models"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="knowledgechunk",
            index=pgvector.django.HnswIndex(
                name="knowledge_chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ),
    ]
