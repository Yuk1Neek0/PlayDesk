# Knowledge Base Chunk Format

This document specifies the source-file format for RAG knowledge-base chunks
and the metadata fields required for ingestion into the `KnowledgeChunk` model.

---

## `KnowledgeChunk` model (from §3.4)

```
KNOWLEDGE_CHUNK {
    int    id        PK
    text   content             -- plain-text chunk body
    vector embedding           -- generated at ingest time
    string category            -- thematic bucket
    string source              -- file path that produced this chunk
    string lang      optional  -- "en" | "zh"
}
```

Embeddings are generated during ingestion by the Django management command
`python manage.py ingest_kb` using OpenAI `text-embedding-3-small`.

---

## Source file format

Each knowledge-base source file lives under `knowledge-base/` and is a
**JSON Lines** file (`*.jsonl`). Every line is a self-contained JSON object
representing one chunk.

### Single-chunk JSON object

```json
{
  "content":  "<plain-text chunk body — 1 to ~300 tokens>",
  "category": "<category slug>",
  "source":   "<relative file path, e.g. knowledge-base/policies-en.jsonl>",
  "lang":     "en"
}
```

### Field reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | `string` | Yes | Plain-text body of the chunk. Keep each chunk focused on a single topic (no more than ~300 tokens). Do NOT include the metadata fields in the content text. |
| `category` | `string` | Yes | Thematic bucket; controls which chunks are retrieved for a given query type. Use the canonical slugs below. |
| `source` | `string` | Yes | Relative path of the file that produced this chunk (used for attribution and re-ingest deduplication). |
| `lang` | `string` | Yes | Language code: `"en"` for English, `"zh"` for Chinese (Simplified). |

### Canonical `category` values

| Slug | Content type |
|------|-------------|
| `game_catalog` | Available titles, platforms, controller counts per station |
| `room_specs` | Room / table capacity, equipment list, hourly rate |
| `business_hours` | Opening hours, holidays, last-entry times |
| `policies` | Cancellation, deposit, refund, outside food, age limits |
| `faq` | Frequently asked questions and concise answers |

---

## Source file naming convention

Files are named `<category>-<lang>.jsonl`:

```
knowledge-base/
  game-catalog-en.jsonl
  game-catalog-zh.jsonl
  room-specs-en.jsonl
  room-specs-zh.jsonl
  business-hours-en.jsonl
  business-hours-zh.jsonl
  policies-en.jsonl
  policies-zh.jsonl
  faq-en.jsonl
  faq-zh.jsonl
```

---

## Ingestion pipeline

```
knowledge-base/*.jsonl
        │
        ▼
python manage.py ingest_kb  (Django management command)
        │
        ├── reads each .jsonl file line by line
        ├── embeds content with text-embedding-3-small
        ├── upserts into knowledge_chunks table (match on source + content hash)
        └── builds HNSW index (or IVFFlat fallback) on the vector column
```

Re-running `ingest_kb` is idempotent; chunks are upserted, not duplicated.

---

## Retrieval contract

At query time the agent:
1. Embeds the user's latest message with the same `text-embedding-3-small` model.
2. Executes a cosine-distance vector search for the top-5 chunks.
3. Injects the matched chunks into the system prompt as:
   ```
   [KB chunk — category: policies, lang: en]
   Cancellation policy: Bookings cancelled more than 24 hours in advance …
   ```

**Design rule (from §1.4):** RAG handles unstructured Q&A (policies, menus,
FAQ). Structured queries (availability, pricing computation, booking state)
must go through SQL tools — never RAG.
