# Epic 1 — Data Model & Persistence (Detailed Plan)

Detailed, implementation-ready plan for Epic 1 of the MVP backlog
(`BACKLOG.md`). Builds on Epic 0 foundations. Architecture per `CLAUDE.md`:
local single-user, Python, **stdlib `sqlite3`** (synchronous) + `sqlite-vec`,
OpenAI embeddings (`text-embedding-3-small`, **1536 dims**).

**Goal of Epic 1:** define the full database schema (relational + vector),
a synchronous data-access layer (repositories), and a swappable `VectorStore`
abstraction — all unit-tested against a temp DB. No business logic yet beyond
CRUD.

**Definition of done**
- All tables + the `vec0` virtual table created idempotently at bootstrap.
- Repository functions for every table with create/read/update where needed.
- `VectorStore` interface with a `sqlite-vec` implementation (pgvector-ready).
- `pytest` green: round-trip CRUD + a KNN vector search on seeded data.

---

## Where vectors are stored (design)

- **Relational content** → `knowledge_chunks` (normal table): chunk text,
  source, metadata.
- **Embeddings** → `knowledge_vectors` (**`sqlite-vec` `vec0` virtual table**),
  living in the *same* `.db` file, keyed by `chunk_id`.
- All vector operations go through a **`VectorStore` interface**
  (`add` / `search` / `delete`), so the future swap to **PostgreSQL +
  pgvector** (vectors as a column, not a virtual table) is an implementation
  change only — relational schema and callers stay the same.

---

## Schema (DDL — final column sets)

> Timestamps stored as ISO-8601 TEXT (UTC). JSON stored as TEXT via
> `json.dumps`. `PRAGMA foreign_keys=ON`.

### `knowledge_chunks` (Task 1.1)
```sql
CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  source_type TEXT NOT NULL,            -- 'file' | 'paste'
  source_name TEXT NOT NULL,            -- filename or pasted-doc label
  chunk_index INTEGER NOT NULL,         -- order within the source
  chunk_text  TEXT NOT NULL,
  token_count INTEGER,
  metadata    TEXT,                     -- JSON (page, offsets, etc.)
  created_at  TEXT NOT NULL
);
```

### `knowledge_vectors` (Task 1.1 — vector store)
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_vectors USING vec0(
  chunk_id  INTEGER PRIMARY KEY,        -- == knowledge_chunks.id
  embedding FLOAT[1536]
);
```
KNN query shape:
```sql
SELECT chunk_id, distance
FROM knowledge_vectors
WHERE embedding MATCH ?              -- query vector
ORDER BY distance
LIMIT ?;                             -- top-k
```

### `emails` (Task 1.2)
```sql
CREATE TABLE IF NOT EXISTS emails (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id      TEXT NOT NULL UNIQUE,   -- Gmail messageId (idempotency key)
  thread_id       TEXT,
  sender          TEXT,
  recipient       TEXT,
  subject         TEXT,
  body_text       TEXT,
  headers         TEXT,                   -- JSON of relevant headers
  received_at     TEXT,
  triage_category TEXT,                   -- 'answerable'|'needs_human'|'no_reply' (null until triaged)
  status          TEXT NOT NULL DEFAULT 'pending',
                  -- pending|triaged|drafted|approved|sent|skipped
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_emails_status ON emails(status);
CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id);
```
The `UNIQUE(message_id)` constraint enforces idempotency at the DB level.

### `replies` (Task 1.3)
```sql
CREATE TABLE IF NOT EXISTS replies (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id       INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
  reply_text     TEXT,
  sources_used   TEXT,                    -- JSON: [{chunk_id, source_name, score}]
  confidence     REAL,
  should_send    INTEGER NOT NULL DEFAULT 0,   -- bool 0/1
  gmail_draft_id TEXT,
  status         TEXT NOT NULL DEFAULT 'draft', -- draft|approved|sent|discarded
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replies_email ON replies(email_id);
```

### `settings` (Task 1.4) — single-row config
```sql
CREATE TABLE IF NOT EXISTS settings (
  id                   INTEGER PRIMARY KEY CHECK (id = 1),
  gmail_connected      INTEGER NOT NULL DEFAULT 0,
  gmail_email          TEXT,
  reply_mode           TEXT NOT NULL DEFAULT 'pilot',   -- pilot|auto
  confidence_threshold REAL NOT NULL DEFAULT 0.75,
  auto_send_rules      TEXT,                            -- JSON: keywords/categories
  updated_at           TEXT NOT NULL
);
```
- Seed row `id=1` with defaults on bootstrap (insert-or-ignore).
- **OAuth tokens are NOT stored here in cleartext.** They go in a separate
  `oauth_tokens` table, **encrypted at rest** (added/owned by Epic 2). Listed
  here only to mark the boundary.

### `sync_state` (Task 1.5) — single-row
```sql
CREATE TABLE IF NOT EXISTS sync_state (
  id              INTEGER PRIMARY KEY CHECK (id = 1),
  last_history_id TEXT,                  -- Gmail historyId for incremental sync
  last_synced_at  TEXT
);
```
- Seed row `id=1` (nulls) on bootstrap.

---

## Task 1.1 — knowledge_chunks + vector table
**Deliverables:** the two tables above; `VectorStore` abstraction (see 1.6);
confirm `vec0` table accepts a 1536-dim vector and returns KNN results.
**Acceptance:** insert 3 chunks + vectors, KNN query returns nearest first.

## Task 1.2 — emails
**Deliverables:** table + indexes; `upsert_email` that no-ops on duplicate
`message_id` (idempotent).
**Acceptance:** inserting the same `message_id` twice yields one row.

## Task 1.3 — replies
**Deliverables:** table + FK cascade; create/update status transitions.
**Acceptance:** deleting an email cascades its replies; status updates persist.

## Task 1.4 — settings
**Deliverables:** single-row table + seed; typed getter/setter that
serializes `auto_send_rules` JSON.
**Acceptance:** defaults present after bootstrap; update round-trips.

## Task 1.5 — sync_state
**Deliverables:** single-row table + seed; `get_history_id` / `set_history_id`.
**Acceptance:** set then get returns the stored `historyId`.

## Task 1.6 — Repositories + VectorStore + tests

**Data-access layout**
```
app/db/
├── connection.py        # (Epic 0) open + load sqlite-vec
├── schema.py            # all DDL above + bootstrap()
├── repositories/
│   ├── __init__.py
│   ├── knowledge.py     # chunks CRUD + ties to VectorStore
│   ├── emails.py        # upsert/get/list/update status
│   ├── replies.py       # create/get/update
│   ├── settings.py      # get/update single row
│   └── sync_state.py    # get/set historyId
└── vector_store/
    ├── __init__.py
    ├── base.py          # VectorStore protocol
    └── sqlite_vec_store.py
```

**`VectorStore` interface (`base.py`)**
```python
class VectorStore(Protocol):
    def add(self, chunk_id: int, embedding: list[float]) -> None: ...
    def search(self, query: list[float], k: int) -> list[tuple[int, float]]:
        """Return [(chunk_id, distance)] nearest first."""
    def delete(self, chunk_id: int) -> None: ...
```
- `SqliteVecStore` implements it against `knowledge_vectors`.
- A future `PgVectorStore` implements the same interface — callers unchanged.

**Conventions**
- Repositories take a `sqlite3.Connection` (injected), return plain dicts/rows;
  no global connection.
- One transaction per write; `row_factory = sqlite3.Row` for dict-like access.
- All timestamps via a shared `now_iso()` helper (UTC).

**Tests (`tests/`)**
- `test_schema.py` — bootstrap creates every table + virtual table (idempotent).
- `test_repo_knowledge.py` — add chunk+vector, KNN search ordering, delete.
- `test_repo_emails.py` — idempotent upsert on `message_id`, status update.
- `test_repo_replies.py` — FK cascade, status transitions.
- `test_repo_settings.py` / `test_repo_sync_state.py` — defaults + round-trip.

---

## Risks / decisions

- **Embedding dimension is fixed at 1536** by `text-embedding-3-small`; changing
  the embedding model later means re-indexing the KB (note for Epic 3).
- **sqlite-vec distance metric** (L2 vs cosine) — pick one and normalize
  embeddings consistently; document it where `search()` is defined.
- **Single-row tables** (`settings`, `sync_state`) use `CHECK (id = 1)` +
  seed-on-bootstrap rather than a key-value store, for typed columns.
- **OAuth token storage** is deliberately deferred to Epic 2 (encrypted
  `oauth_tokens` table); Epic 1 only reserves the boundary.

## Definition of done checklist (Epic 1)

- [ ] All tables + `knowledge_vectors` virtual table bootstrap idempotently.
- [ ] Repositories for chunks, emails, replies, settings, sync_state.
- [ ] `VectorStore` interface + `SqliteVecStore`; KNN search verified.
- [ ] `emails.message_id` idempotency enforced and tested.
- [ ] Single-row `settings`/`sync_state` seeded with defaults.
- [ ] `pytest` green: CRUD round-trips + vector search on seeded data.
