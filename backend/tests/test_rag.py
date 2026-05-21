"""
Tests for the RAG layer (Issue #11).

All tests mock the embedding client — no OpenAI API calls in CI.
DB tests require a live Postgres instance; they are skipped automatically
when the DB is unavailable (pytest-django marks handle that).
"""

from __future__ import annotations

import math

import pytest

import rag.embeddings as emb_module
from rag.embeddings import FakeEmbeddingClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def use_fake_embeddings():
    """Replace the module-level embedding client with a fake for every test."""
    emb_module.set_embedding_client(FakeEmbeddingClient())
    yield
    emb_module.reset_embedding_client()


@pytest.fixture()
def store_and_resource(db):
    from core.models import Resource, Store

    store = Store.objects.create(name="RAG Test Store", timezone="UTC", business_hours={})
    resource = Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Test",
        capacity=4,
        price_per_hour="58.00",
    )
    return store, resource


# ---------------------------------------------------------------------------
# Unit tests — FakeEmbeddingClient
# ---------------------------------------------------------------------------


class TestFakeEmbeddingClient:
    def test_embed_returns_correct_dimension(self):
        client = FakeEmbeddingClient(dimensions=1536)
        vec = client.embed("hello world")
        assert len(vec) == 1536

    def test_embed_is_normalised(self):
        client = FakeEmbeddingClient(dimensions=1536)
        vec = client.embed("normalised?")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_embed_is_deterministic(self):
        client = FakeEmbeddingClient(dimensions=1536)
        assert client.embed("foo") == client.embed("foo")

    def test_different_texts_produce_different_vectors(self):
        client = FakeEmbeddingClient(dimensions=1536)
        assert client.embed("apple") != client.embed("banana")

    def test_embed_batch_matches_individual_calls(self):
        client = FakeEmbeddingClient(dimensions=1536)
        texts = ["alpha", "beta", "gamma"]
        batch = client.embed_batch(texts)
        individual = [client.embed(t) for t in texts]
        assert batch == individual

    def test_embed_batch_empty(self):
        client = FakeEmbeddingClient(dimensions=1536)
        assert client.embed_batch([]) == []


# ---------------------------------------------------------------------------
# Unit tests — get/set/reset embedding client
# ---------------------------------------------------------------------------


class TestEmbeddingClientRegistry:
    def test_set_and_get(self):
        fake = FakeEmbeddingClient(dimensions=8)
        emb_module.set_embedding_client(fake)
        assert emb_module.get_embedding_client() is fake

    def test_reset_clears_singleton(self):
        emb_module.reset_embedding_client()
        # After reset the next call should create a new OpenAI client —
        # but we don't want to actually instantiate it in tests, so just
        # verify the internal _client is None after reset.
        assert emb_module._client is None
        # Restore fake so other tests are unaffected
        emb_module.set_embedding_client(FakeEmbeddingClient())


# ---------------------------------------------------------------------------
# Integration tests — ingest + retrieve (require DB)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIngest:
    def test_ingest_creates_chunks(self, tmp_path):
        """Management command creates KnowledgeChunk rows from a JSONL file."""
        import json

        from django.core.management import call_command

        from core.models import KnowledgeChunk

        # Write a tiny JSONL file
        kb_dir = tmp_path / "kb"
        kb_dir.mkdir()
        chunks = [
            {
                "content": "Outside food is not allowed.",
                "category": "policies",
                "source": "kb/policies-en.jsonl",
                "lang": "en",
            },
            {
                "content": "We close at 11 PM on weekdays.",
                "category": "business_hours",
                "source": "kb/policies-en.jsonl",
                "lang": "en",
            },
        ]
        jsonl_path = kb_dir / "policies-en.jsonl"
        with jsonl_path.open("w") as f:
            for chunk in chunks:
                f.write(json.dumps(chunk) + "\n")

        assert KnowledgeChunk.objects.count() == 0
        call_command("ingest_kb", kb_dir=str(kb_dir), verbosity=0)
        assert KnowledgeChunk.objects.count() == 2

    def test_ingest_is_idempotent(self, tmp_path):
        """Running ingest_kb twice does not create duplicate chunks."""
        import json

        from django.core.management import call_command

        from core.models import KnowledgeChunk

        kb_dir = tmp_path / "kb"
        kb_dir.mkdir()
        chunk = {
            "content": "Deposits are 50% of total fee.",
            "category": "policies",
            "source": "kb/idempotent-test.jsonl",
            "lang": "en",
        }
        jsonl_path = kb_dir / "idempotent-test.jsonl"
        with jsonl_path.open("w") as f:
            f.write(json.dumps(chunk) + "\n")

        call_command("ingest_kb", kb_dir=str(kb_dir), verbosity=0)
        call_command("ingest_kb", kb_dir=str(kb_dir), verbosity=0)

        assert KnowledgeChunk.objects.filter(source="kb/idempotent-test.jsonl").count() == 1

    def test_ingest_stores_correct_fields(self, tmp_path):
        """Ingest stores content, category, source and lang correctly."""
        import json

        from django.core.management import call_command

        from core.models import KnowledgeChunk

        kb_dir = tmp_path / "kb"
        kb_dir.mkdir()
        chunk = {
            "content": "PS5 stations cost CNY 58/hr.",
            "category": "game_catalog",
            "source": "kb/game-catalog-en.jsonl",
            "lang": "en",
        }
        jsonl_path = kb_dir / "game-catalog-en.jsonl"
        with jsonl_path.open("w") as f:
            f.write(json.dumps(chunk) + "\n")

        call_command("ingest_kb", kb_dir=str(kb_dir), verbosity=0)

        obj = KnowledgeChunk.objects.get()
        assert obj.content == chunk["content"]
        assert obj.category == chunk["category"]
        assert obj.source == chunk["source"]
        assert obj.lang == chunk["lang"]
        assert obj.embedding is not None
        assert len(obj.embedding) == 1536


@pytest.mark.django_db
class TestRetrieve:
    def _seed_chunks(self):
        """Insert a small set of KnowledgeChunks using the fake embedding client."""
        from core.models import KnowledgeChunk
        from rag.embeddings import get_embedding_client

        client = get_embedding_client()
        rows = [
            ("Outside food and beverages are not permitted.", "policies", "s1.jsonl", "en"),
            ("We open at 10 AM and close at 11 PM.", "business_hours", "s2.jsonl", "en"),
            ("PS5 stations cost CNY 58 per hour.", "game_catalog", "s3.jsonl", "en"),
            ("室外食物不允许带入。", "policies", "s4.jsonl", "zh"),
            ("我们的营业时间是早上10点到晚上11点。", "business_hours", "s5.jsonl", "zh"),
        ]
        for content, category, source, lang in rows:
            KnowledgeChunk.objects.create(
                content=content,
                embedding=client.embed(content),
                category=category,
                source=source,
                lang=lang,
            )

    def test_retrieve_returns_results(self):
        from rag.retriever import retrieve

        self._seed_chunks()
        results = retrieve("outside food policy", k=3)
        assert len(results) <= 3
        assert len(results) >= 1

    def test_retrieve_result_structure(self):
        from rag.retriever import retrieve

        self._seed_chunks()
        results = retrieve("food policy")
        for r in results:
            assert "chunk_id" in r
            assert "content" in r
            assert "category" in r
            assert "source" in r
            assert "lang" in r
            assert "score" in r
            assert 0.0 <= r["score"] <= 1.0

    def test_retrieve_lang_filter(self):
        from rag.retriever import retrieve

        self._seed_chunks()
        results = retrieve("food", k=5, lang="zh")
        assert all(r["lang"] == "zh" for r in results)

    def test_retrieve_category_filter(self):
        from rag.retriever import retrieve

        self._seed_chunks()
        results = retrieve("opening hours", k=5, category="business_hours")
        assert all(r["category"] == "business_hours" for r in results)

    def test_retrieve_empty_db(self):
        from rag.retriever import retrieve

        results = retrieve("anything", k=5)
        assert results == []

    def test_retrieve_k_limits_results(self):
        from rag.retriever import retrieve

        self._seed_chunks()
        results = retrieve("policy", k=2)
        assert len(results) <= 2
