# Epics 3 & 4 — Knowledge Base + RAG Pipeline — Detailed Plan

Combined plan for Epic 3 (knowledge ingestion) and Epic 4 (RAG pipeline),
which sit on opposite ends of the **same retrieval seam**. Builds on Epics 0–2.
Architecture per `CLAUDE.md`: local single-user, Python, SQLite + `sqlite-vec`,
OpenAI (provider-swappable), mail behind the `MailProvider` facade.

```
Epic 3 (write path)                      Epic 4 (read path)
files/text ─► parse ─► chunk ─► embed ─► [ knowledge_chunks + knowledge_vectors ]
                                              ▲                    │
                                        same model,         embed query ─► search ─► score
                                        same dim,                                  │
                                        same store                          confidence gate
                                                                                   │
                                                            triage ─► retrieve ─► generate ─► reply row
```

## Why one plan: the shared contract

Both epics must agree on three things, so they live in **shared modules** that
neither epic redefines:

1. **Embedding model & dimension** — both call the same `provider.embed()`
   (`text-embedding-3-small`, 1536-dim). If the model changes, the KB must be
   re-indexed (retrieval would otherwise compare incompatible vectors).
2. **Distance → score** — `sqlite-vec` returns **L2 distance**; OpenAI
   embeddings are unit-normalized, so cosine similarity is
   `score = 1 - distance² / 2`. A single `app/rag/scoring.py` owns this
   conversion **and** the confidence gate; the ingest path doesn't need it, the
   retrieve path and the UI both consume it.
3. **The store** — Epic 1's `knowledge` repo + `VectorStore` is the only way in
   and out. Epic 3 calls `add_chunk` / `delete_*`; Epic 4 calls `search`.

> **One additive schema change** (forward-compat seam for multi-stream
> routing, see `docs/scaling-and-routing.md`): add a nullable `namespace`
> column to `knowledge_chunks` (default `"default"`). Everything else —
> `knowledge_vectors`, `emails.triage_category/status`, and
> `replies.{confidence,sources_used,should_send}` — already exists from Epic 1.
> The MVP uses the single `"default"` namespace; a later epic adds the
> `streams` table that maps topics → namespaces + per-stream workflow.

## Proposed module layout
```
app/rag/
├── __init__.py
├── parsers.py     # E3: PDF/DOCX/TXT -> text
├── chunking.py    # E3: split text into overlapping chunks
├── ingest.py      # E3: parse -> chunk -> embed -> knowledge.add_chunk
├── scoring.py     # SHARED: distance<->similarity + confidence gate
├── retrieval.py   # E4: embed query -> knowledge.search -> scored hits
├── guards.py      # E4: rule-based safe-sender / loop guards (uses E2 headers)
├── triage.py      # E4: LLM classification (answerable/needs_human/no_reply)
├── generate.py    # E4: grounded generation -> structured output
└── pipeline.py    # E4: orchestrate guards->triage->retrieve->gate->generate->persist
app/routers/knowledge.py   # E3: upload / paste / list / delete (JSON; UI in E6)
```

## New config (`app/config.py` + `.env.example`)
| Field             | Default | Used by | Notes                                  |
| ----------------- | ------- | ------- | -------------------------------------- |
| `chunk_size`      | `1000`  | E3      | characters per chunk                   |
| `chunk_overlap`   | `150`   | E3      | character overlap between chunks       |
| `retrieval_top_k` | `5`     | E4      | neighbours fetched per query           |
| `confidence_threshold` | `0.75` (exists) | E4 | min top-similarity to draft a reply |

## Shared data shapes (`dataclass`es)
```python
# scoring.py / retrieval.py
@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    source_name: str
    text: str
    score: float        # cosine similarity in [0, 1]
    distance: float     # raw L2 from sqlite-vec

# triage.py — category is an OPEN string (stored as TEXT). The enum below is
# just the MVP's known set; a later multi-stream epic adds stream names as
# additional categories without a code/schema change.
class TriageCategory(str, Enum):
    ANSWERABLE = "answerable"
    NEEDS_HUMAN = "needs_human"
    NO_REPLY = "no_reply"

@dataclass(frozen=True)
class TriageResult:
    category: str   # one of TriageCategory today; open for future stream names
    reason: str

# generate.py
@dataclass(frozen=True)
class GenerationResult:
    reply: str
    sources_used: list[dict]   # [{chunk_id, source_name, score}]
    confidence: float
    should_send: bool
```

---

# Epic 3 — Knowledge base ingestion

**Goal:** turn uploaded files / pasted text into embedded, searchable chunks in
the existing knowledge store. **DoD:** upload a PDF/DOCX/TXT or paste text →
chunks embedded and indexed; list/search/delete works; offline tests pass.

**New deps:** `pypdf`, `python-docx`.

### 3.1 (P0) Parsers (`parsers.py`)
- `extract_text(filename, data: bytes) -> str` dispatching by extension:
  `pypdf` (PDF), `python-docx` (DOCX), UTF-8 decode (TXT). Unsupported → clear
  error. **Acceptance:** tiny fixture files parse to expected text.

### 3.2 (P0) Chunking (`chunking.py`)
- `chunk_text(text, size, overlap) -> list[str]` — character windows with
  overlap, trimming whitespace, dropping empties. **Acceptance:** boundary
  tests (short text → 1 chunk; overlap correct; deterministic count).

### 3.3 (P0) Ingest service (`ingest.py`)
- Add the nullable `namespace` column to `knowledge_chunks` (default
  `"default"`) in `schema.py`; thread an optional `namespace="default"` param
  through the `knowledge` repo (`add_chunk`, `list_chunks`, `delete_by_source`,
  `search`). No production DB exists yet, so updating the `CREATE TABLE` is
  sufficient (no migration needed).
- `ingest_document(conn, store, provider, *, source_type, source_name, text,
  namespace="default")` → chunk → `provider.embed(batch)` →
  `knowledge.add_chunk(...)` per chunk; returns chunk count. Idempotency:
  re-ingesting the same `(namespace, source_name)` replaces it
  (`delete_by_source` first). **Acceptance:** ingest with the fake provider
  stores N chunks + N vectors; re-ingest doesn't duplicate; chunks carry the
  namespace.

### 3.4 (P0) KB management routes (`routers/knowledge.py`)
- `POST /kb/upload` (multipart file), `POST /kb/paste` (json text+label),
  `GET /kb` (list sources w/ chunk counts), `DELETE /kb/{source_name}`.
  Return JSON; Epic 6 builds the UI on top. **Acceptance:** route tests via
  `TestClient` with the fake provider injected (no OpenAI calls).

### 3.5 (P1) Tests
Parsers (fixtures), chunking boundaries, ingest + re-ingest idempotency,
routes, delete removes chunks **and** vectors (search returns nothing).

---

# Epic 4 — RAG pipeline (triage → retrieve → gate → generate)

**Goal:** for an ingested email, decide whether/how to answer and produce a
grounded draft reply stored in `replies`. **DoD:** end-to-end
`process_email` runs offline with fakes: guards + triage classify, retrieval
scores, the gate blocks low-confidence answers, generation returns structured
output, and the email/reply rows are updated. **Stops before sending** — Gmail
draft/send is Epic 7.

### 4.0 (P0) Scoring + gate (`scoring.py`) — *shared seam*
- `distance_to_score(distance) -> float` = `1 - distance²/2`, clamped to [0,1].
- `passes_gate(top_score, threshold) -> bool`. **Acceptance:** distance 0 → 1.0;
  larger distance → lower score; gate honors the threshold.

### 4.1 (P0) Safe-sender / loop guards (`guards.py`)
- Pure function over `EmailMessage`/email row headers (surfaced by Epic 2):
  skip when `auto-submitted` not `no`, `list-id` present, `precedence` in
  {bulk,list,junk}, sender is our own account, or sender looks like
  `no-reply@`. Returns `TriageResult(NO_REPLY, reason)` or `None`.
  **Acceptance:** each guard triggers on a crafted header set; clean mail passes.

### 4.2 (P0) LLM triage (`triage.py`)
- For mail that clears the guards, `classify(provider, email) -> TriageResult`
  via `provider.generate(..., json_schema=...)` returning one of the three
  categories + reason. **Acceptance:** with a fake LLM returning fixed JSON,
  the category parses; malformed output defaults safely to `needs_human`.

### 4.3 (P0) Retrieval (`retrieval.py`)
- `retrieve(conn, store, provider, query_text, k, namespace="default") ->
  list[RetrievedChunk]`: `provider.embed([query])` → `knowledge.search`
  (filtered to `namespace`) → wrap with `distance_to_score`. **Acceptance:**
  nearest chunk has the highest score; ordering matches distance; results are
  scoped to the namespace.

### 4.4 (P0) Confidence gate integration
- In the pipeline: if no chunks or `top.score < threshold`, do **not** generate;
  downgrade to `needs_human`. **Acceptance:** empty KB / low score → no reply
  text, email flagged `needs_human`.

### 4.5 (P0) Grounded generation (`generate.py`)
- `generate_reply(provider, email, chunks, thread) -> GenerationResult` with a
  prompt that: answers **only** from provided chunks, defers if insufficient,
  cites sources, and returns structured JSON. Includes thread context when
  provided. **Acceptance:** fake LLM JSON parses into `GenerationResult`;
  prompt contains the retrieved chunk text + thread.

### 4.6 (P0) Pipeline orchestration (`pipeline.py`)
- `process_email(conn, store, provider, email_row, *, thread=None) -> dict`:
  guards → triage → (if answerable) retrieve → gate → generate → persist.
  Persists via existing repos: `emails.set_triage(...)`, `emails.update_status`
  (`drafted` / `skipped` / `needs_human`), and `replies.create_reply(...)` with
  `sources_used`, `confidence`, `should_send`. **Thread context** is fetched by
  the caller (Epic 5 scheduler) through `MailProvider.get_thread` and passed in,
  so the pipeline stays mail-agnostic and offline-testable.
  **Acceptance:** answerable+confident → `drafted` + reply row with sources;
  guarded/low-confidence → no reply row, correct status.

### 4.7 (P1) Tests
Guards matrix, triage parsing (incl. malformed-safe default), retrieval
scoring/order, gate behavior, generation parsing + prompt grounding, and a
`process_email` end-to-end across all branches with fake provider + fake KB.

---

## Cross-epic consistency checklist
- [ ] Ingest (E3) and retrieval (E4) call the **same** `provider.embed()`.
- [ ] Only `scoring.py` converts distance↔score; gate uses
  `settings.confidence_threshold`.
- [ ] Both paths go through the Epic 1 `knowledge` repo + `VectorStore`.
- [ ] Triage guards consume the headers Epic 2 surfaces (no re-parsing).
- [ ] KB carries a `namespace` (default `"default"`); retrieval filters by it.
- [ ] Triage category is an open string (TEXT), not a closed enum in the DB.
- [ ] Pipeline stops at a stored draft reply; sending is Epic 7.

## Risks / decisions
- **Char vs token chunking.** MVP uses character windows (no tokenizer dep);
  revisit with `tiktoken` if chunk sizing vs. embedding limits becomes an issue.
- **Score calibration.** `1 - d²/2` assumes unit-normalized embeddings (true for
  OpenAI). If a provider returns un-normalized vectors, normalize before store
  **and** query, or the threshold loses meaning.
- **Triage cost.** One LLM call per new email; acceptable at single-user volume.
  Guards run first to avoid LLM calls on obvious bulk mail.
- **Malformed LLM JSON.** Generation/triage must fail safe (defer to
  `needs_human`) rather than raise into the scheduler.
- **Re-index on model change.** Document that changing `embedding_model`
  requires clearing + re-ingesting the KB.
