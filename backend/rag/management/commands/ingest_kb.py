"""
Django management command: ingest_kb

Reads all *.jsonl files from <repo-root>/knowledge-base/, embeds each chunk
with the configured embedding client, and upserts into the KnowledgeChunk table.

Re-running is idempotent: chunks are matched by (source, content_hash) so
unchanged content is never re-embedded.

Usage:
    python manage.py ingest_kb
    python manage.py ingest_kb --kb-dir /path/to/kb   # override KB directory
    python manage.py ingest_kb --batch-size 50         # tune OpenAI batch size
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import KnowledgeChunk
from rag.embeddings import get_embedding_client


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Command(BaseCommand):
    help = "Ingest knowledge-base JSONL files into KnowledgeChunk (idempotent)."

    def add_arguments(self, parser):
        # Default KB dir: two levels up from manage.py → project root / knowledge-base
        default_kb_dir = Path(__file__).resolve().parents[6] / "knowledge-base"
        parser.add_argument(
            "--kb-dir",
            type=Path,
            default=default_kb_dir,
            help="Path to the directory containing *.jsonl knowledge-base files.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=32,
            help="Number of chunks to embed in a single API call (default: 32).",
        )

    def handle(self, *args, **options):
        # call_command() bypasses argparse type coercion, so kb_dir may be a str.
        kb_dir = Path(options["kb_dir"])
        batch_size: int = options["batch_size"]

        if not kb_dir.is_dir():
            raise CommandError(f"KB directory not found: {kb_dir}")

        jsonl_files = sorted(kb_dir.glob("*.jsonl"))
        if not jsonl_files:
            self.stderr.write(self.style.WARNING(f"No *.jsonl files found in {kb_dir}"))
            return

        self.stdout.write(f"Found {len(jsonl_files)} JSONL file(s) in {kb_dir}")

        client = get_embedding_client()

        total_created = 0
        total_skipped = 0

        for jsonl_path in jsonl_files:
            self.stdout.write(f"  Processing {jsonl_path.name} …")
            chunks = _load_jsonl(jsonl_path, self.stderr)

            if not chunks:
                continue

            # Annotate each chunk with its content hash for deduplication
            for chunk in chunks:
                chunk["_hash"] = _sha256(chunk["content"])

            # Determine which chunks already exist in the DB by hashing stored content.
            existing_content_hashes: set[str] = {
                _sha256(c)
                for c in KnowledgeChunk.objects.filter(source=chunks[0]["source"]).values_list(
                    "content", flat=True
                )
            }

            new_chunks = [c for c in chunks if c["_hash"] not in existing_content_hashes]
            skip_count = len(chunks) - len(new_chunks)
            total_skipped += skip_count

            if skip_count:
                self.stdout.write(f"    Skipping {skip_count} already-ingested chunk(s).")

            if not new_chunks:
                continue

            # Embed in batches
            texts = [c["content"] for c in new_chunks]
            embeddings = _embed_in_batches(client, texts, batch_size, self.stdout)

            # Bulk-create
            to_create = []
            for chunk, embedding in zip(new_chunks, embeddings):
                to_create.append(
                    KnowledgeChunk(
                        content=chunk["content"],
                        embedding=embedding,
                        category=chunk.get("category", ""),
                        source=chunk.get("source", str(jsonl_path)),
                        lang=chunk.get("lang", "en"),
                    )
                )

            KnowledgeChunk.objects.bulk_create(to_create)
            total_created += len(to_create)
            self.stdout.write(self.style.SUCCESS(f"    Created {len(to_create)} new chunk(s)."))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created: {total_created}, Skipped (already present): {total_skipped}."
            )
        )


def _load_jsonl(path: Path, stderr) -> list[dict]:
    """Parse a JSONL file; skip malformed lines with a warning."""
    chunks = []
    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                stderr.write(f"    WARNING: skipping malformed line {lineno} in {path.name}: {exc}")
                continue

            required = {"content", "category", "source", "lang"}
            missing = required - obj.keys()
            if missing:
                stderr.write(
                    f"    WARNING: line {lineno} in {path.name} missing fields {missing}; skipping."
                )
                continue

            chunks.append(obj)

    return chunks


def _embed_in_batches(
    client,
    texts: list[str],
    batch_size: int,
    stdout,
) -> list[list[float]]:
    """Embed *texts* in batches of *batch_size*, returning a flat list of vectors."""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        stdout.write(
            f"    Embedding batch {i // batch_size + 1} ({len(batch)} chunk(s)) …",
            ending="\r",
        )
        sys.stdout.flush()
        all_embeddings.extend(client.embed_batch(batch))
    stdout.write("")  # newline after \r progress
    return all_embeddings
