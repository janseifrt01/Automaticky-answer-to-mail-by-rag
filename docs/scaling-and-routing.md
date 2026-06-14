# Scaling & Multi-Stream Routing — Design Notes

Forward-looking notes (not MVP scope) on (a) cost/latency at higher volume and
(b) supporting **multiple topical streams** ("burners") — each with its own
knowledge base and workflow. Captures decisions so the MVP leaves the right
seams open. See `CLAUDE.md` and `docs/epics-3-4-rag.md` for the current design.

## 1. Cost & latency at hundreds of emails/day

At single-mailbox / hundreds-per-day volume, the public LLM is **not** the
limiter. Rough model with the default `gpt-4o-mini` + `text-embedding-3-small`
(approximate public pricing — **verify against current rate cards**):

| Stage | Tokens/email | |
| --- | --- | --- |
| Triage | ~700 in / 50 out | guards filter bulk first |
| Query embedding | ~500 | |
| Generation | ~2,800 in / 300 out | system + top-k chunks + thread + email |

- **~$0.0007 per processed email** → **300/day ≈ ~$6/month**, **1,000/day ≈
  ~$22/month**. A frontier model (~15–20×) → ~$100–150/month at 300/day.
- **Embeddings are negligible** (~$0.003/day at 300 emails); KB embedding is a
  one-time per-document cost.
- **Latency ~4–6 s/email** is irrelevant in the async polling design —
  arrival rate is decoupled from processing rate.
- **The real ceiling at scale is provider rate limits (RPM/TPM)**, handled by
  concurrency control + the existing retry/backoff + batched embeddings.

## 2. Extensibility levers (already isolated by current seams)

- **`embed()` / `generate()` interface** → swap to Claude or **local
  embeddings** (`bge`/`sentence-transformers`) for cost/privacy. *Changing the
  embedding model requires re-indexing the KB.*
- **Two-tier model routing** — cheap model for triage + easy replies, escalate
  to a stronger model only on low confidence/complex mail.
- **Prompt caching** — static system prompt + KB context as cached input tokens.
- **Worker swap** — APScheduler → Celery/arq for parallel workers.
- **Postgres + pgvector** — already behind the `VectorStore` interface.

## 3. Multiple streams ("burners") — per-topic KB + workflow

Goal: define N streams (e.g. *offers/quotes*, *order inquiries*, *complaints*),
each with its **own KB**, **own prompt/workflow**, and **own policy**. An email
is **routed** to one stream, which drives retrieval + generation + send policy.
This is **additive** — every overridable piece is already a separate module.

### Proposed `streams` table (post-MVP)
| Column | Purpose |
| --- | --- |
| `name`, `description`, `enabled`, `priority` | identity + match order |
| `match_rules` | keywords / sender patterns / LLM label |
| `kb_namespace` | which KB slice to retrieve from |
| `prompt_template` | grounded-generation instructions for this stream |
| `reply_mode`, `confidence_threshold`, `model` | per-stream policy overrides |
| `force_human` | e.g. complaints → always pilot/needs-human |

### Module impact (all already separated in `app/rag/`)
- **`triage.py` → `router.py`**: classify into one of the defined streams (or
  `no_reply` / `needs_human`). Rule-based match first, LLM label fallback — same
  structure, category set becomes data-driven instead of a fixed enum.
- **`knowledge_chunks` + `namespace`**: retrieval filters by the stream's
  `kb_namespace`. `sqlite-vec` `vec0` supports a partition column for efficient
  filtered KNN (or post-filter chunk_ids for a simpler first cut).
- **`retrieval.py`** takes a namespace filter; **`generate.py`** takes the
  stream's prompt template; gate/mode read stream overrides, falling back to
  global `settings`.

### Cheap forward-compatible seams to add in the MVP
1. **Nullable `namespace` column on `knowledge_chunks`** (default `"default"`) —
   KB is namespace-ready while the MVP uses a single namespace.
2. **Triage result = open category string + reason** (not a hard 3-value enum
   wired across the code) — routing into N streams later is a data change.

Everything else (the `streams` table, the router, per-stream prompts/policy, the
KB-namespace UI) is deferred to a dedicated post-MVP epic.
