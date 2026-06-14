# CLAUDE.md

Guidance for AI assistants (Claude Code) working in this repository.

## Project

**RAG Mail Auto-Reply** — a single-user email assistant that reads a Gmail
inbox, retrieves relevant context from a user-provided knowledge base, and
drafts replies using AI (Retrieval-Augmented Generation: search the knowledge
base, then generate).

Runs **locally for one user / one inbox**. Web app only (fully responsive).
Default behavior is **Pilot mode** (every draft is reviewed before sending);
**Auto mode** can send automatically, but only when all guards pass
(see *Safety & guardrails*).

## Status

> **MVP implemented (Epics 0–7).** The full loop works end-to-end: scheduled
> Gmail sync → triage → retrieve → confidence gate → grounded draft →
> review/edit → send (Pilot) or gated Auto-send. ~133 tests, all offline.
> This document now reflects the actual codebase; keep it in sync as code
> changes. Per-epic design notes live in `docs/`; the task list in `BACKLOG.md`.

## How it works (pipeline)

1. **Connect Gmail** — link a Gmail account via Google OAuth2 (minimal scopes).
2. **Build a knowledge base** — upload PDF/DOCX/TXT or paste text; content is
   chunked, embedded, and indexed.
3. **Incremental inbox sync** — a scheduled job uses the Gmail **History API
   (`historyId`)** to fetch only new messages, ~every 5 min. Processed
   `messageId`s are recorded for idempotency (no double-processing / sending).
4. **Triage** — classify each new email: *answerable-from-KB / needs-human /
   no-reply-needed*. Apply safe-sender guards (skip automated senders, lists,
   loops). Non-answerable mail is flagged, never auto-drafted.
5. **Retrieve + gate** — embed the email (with thread context), vector-search
   the knowledge base. If the top results fall below the **confidence
   threshold**, do **not** draft — flag "no confident answer, needs human."
6. **Generate (grounded)** — prompt the model to answer **only** from retrieved
   context and return structured output: `{reply, sources_used, confidence,
   should_send}`.
7. **Review & send** — Pilot: a Gmail **draft** is created and shown in the
   dashboard with cited sources; user approves / edits / discards. Auto: send
   only if triage + confidence + safe-sender guards all pass.

## Stack (Python, local single-user)

| Layer                 | Technology                                                        |
| --------------------- | ---------------------------------------------------------------- |
| Backend / API         | **FastAPI** (async, OpenAPI built-in)                            |
| Database              | **SQLite** (single-file, no server to operate)                   |
| Vector search         | **`sqlite-vec`** extension (vectors live in the same SQLite DB)  |
| Scheduling            | **APScheduler** in-process, ~5 min interval                      |
| AI embeddings         | OpenAI `text-embedding-3-small` (provider-swappable)             |
| AI reply generation   | OpenAI `gpt-4o-mini` (provider-swappable)                        |
| Email integration     | Gmail API — `google-api-python-client` + `google-auth-oauthlib` |
| File parsing          | `pypdf` (PDF), `python-docx` (DOCX), plain read (TXT)           |
| Frontend              | FastAPI + Jinja2 + HTMX + Tailwind (no JS build)                 |
| Config / secrets      | `.env` + `pydantic-settings`; OAuth tokens encrypted at rest     |

**Design notes / decisions:**

- **SQLite + sqlite-vec**: it's a single-user local app, so a single-file DB
  removes all DB-server ops while still giving vector search alongside the
  relational data. (Postgres + pgvector would only be warranted if this became
  a hosted multi-user service.)
- **In-process APScheduler**: simplest for local use. A separate worker
  (Celery/arq) is unnecessary at single-user volume.
- **Provider stays pluggable**: keep one `embed()` / `generate()` interface so
  OpenAI ↔ Claude is a config swap, not a rewrite. OpenAI is the documented
  default unless the user changes it.
- **Mail behind a `MailProvider` facade**: receiving/sending go through a
  provider-agnostic interface (domain models, not Gmail types). Gmail/OAuth2 is
  the only v1 implementation; a future Outlook/IMAP provider is a new class, not
  a rewrite. See `docs/epic-2-mail-facade.md`.
- **HTMX frontend**: live-ish queue + approve/edit/send actions with no
  separate JS build, which fits a single-user review dashboard.

## Codebase layout & key modules

```
app/
  main.py              # app factory + lifespan: opens DB, bootstraps, starts scheduler
  config.py            # Settings (pydantic-settings); get_settings()
  deps.py              # FastAPI deps: get_db / get_embedder / get_mail / get_vector_store
  db/
    connection.py      # connect(): sqlite-vec load, WAL, busy_timeout, check_same_thread
    schema.py          # all DDL + idempotent bootstrap()
    repositories/      # one module per table (knowledge, emails, replies, settings, sync_state, credentials)
    vector_store/      # VectorStore protocol + SqliteVecStore (vec0 KNN)
  providers/           # EmbeddingProvider/LLMProvider protocols + OpenAIProvider + get_provider()
  mail/
    base.py models.py  # MailProvider facade + domain models (EmailMessage/OutgoingMessage/SyncResult)
    factory.py         # get_mail_provider() / build_gmail_client()
    crypto.py          # TokenCipher (Fernet) for credential encryption
    ingest.py          # sync_once(): fetch new mail → emails repo (idempotent)
    sender.py          # build_outgoing / send_reply / create_gmail_draft / should_auto_send / dispatch
    gmail/             # auth (OAuth2), client (API wrapper + retry), provider (mapping)
  rag/
    parsers.py chunking.py ingest.py   # KB ingestion (write side)
    scoring.py         # distance↔similarity + confidence gate (shared seam)
    retrieval.py guards.py triage.py generate.py pipeline.py   # read side
  scheduler/
    runner.py          # run_cycle(): async sync → guard → concurrent process → sequential dispatch
    service.py         # AsyncIOScheduler + run_once()
  routers/             # health, auth (OAuth), knowledge (JSON KB API), sync, web (HTML/HTMX)
  templates/           # Jinja2 + HTMX UI
tests/                 # pytest; conftest.py has offline fakes (FakeProvider, FakeMailProvider, ScriptedProvider)
docs/                  # per-epic design notes
```

## Install / run / test

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # set OPENAI_API_KEY, TOKEN_ENCRYPTION_KEY, Google creds
uvicorn app.main:app --reload   # UI at http://127.0.0.1:8000/
pytest                          # full suite, fully offline
ruff check .                    # lint (line length 88; B008 ignored for FastAPI Depends)
```

See `README.md` for the Google Cloud OAuth setup steps.

## Data flow (end-to-end)

`scheduler.run_cycle` (every ~5 min, or `POST /sync/now`):
1. `mail.ingest.sync_once` → new emails stored `pending` (idempotent on `messageId`).
2. **Sequential:** `rag.guards.check_guards` skips bulk/auto mail; for survivors,
   fetch Gmail thread context (httplib2 isn't thread-safe → sequential).
3. **Concurrent** (`asyncio.to_thread`, bounded by `max_concurrency`):
   `rag.pipeline.process_email` = triage → retrieve → gate → generate → persist a
   `replies` row + set email `drafted`/`needs_human`/`skipped`. This phase is
   mail-agnostic (OpenAI + SQLite only), so it parallelizes safely.
4. **Sequential dispatch** (`mail.sender.dispatch`): Pilot → create a Gmail draft;
   Auto → `send_reply` if `should_auto_send` passes.
Pilot review happens in the web dashboard; "Approve & Send" calls `sender.send_reply`.

## Conventions

- **Repositories** take a `sqlite3.Connection` (injected), one transaction per
  write, return plain dicts; JSON columns (de)serialized at the repo boundary.
- **Mail vs LLM threading:** Gmail/httplib2 calls are always **sequential**;
  only OpenAI + DB work runs **concurrently**. Never share a Gmail service/conn
  across threads — each concurrent worker opens its own SQLite connection.
- **Offline tests:** no network. Use the fakes in `tests/conftest.py`; override
  `get_embedder` / `get_mail` via `app.dependency_overrides` for route tests.
- **Provider stays OpenAI** by default (not Claude) — see below.

## RAG & generation rules

- **Triage before retrieval** — classify the email; skip mail that needs a
  human or no reply at all.
- **Confidence gate** — never draft when top retrieval scores are below the
  configured threshold; flag for human instead of guessing.
- **Grounded answers only** — the generation prompt must instruct the model to
  use only retrieved context and to defer when context is insufficient.
- **Structured output** — `{reply, sources_used, confidence, should_send}`;
  cited sources are surfaced in the review UI for verification.
- **Thread context** — include prior messages in the Gmail thread as context;
  set `In-Reply-To` / `References` and reuse the `threadId` so replies thread
  correctly.

## Safety & guardrails

- **Pilot by default**; Auto-send requires triage + confidence + safe-sender
  guards to all pass.
- **Safe-sender / loop prevention** — never reply to automated senders or
  lists (`Auto-Submitted`, `List-Id`, `Precedence: bulk`), other auto-replies,
  or our own sent mail.
- **Idempotency** — track processed `messageId`s; never draft or send twice for
  the same message.
- **Native Gmail drafts** as the safety net in Pilot mode — nothing is sent
  without an explicit action.
- **Minimal OAuth scopes** and OAuth tokens encrypted at rest.

## Data model (SQLite)

- **knowledge_chunks** — chunked KB content + source/metadata, plus a
  `namespace` (default `"default"`) — a forward-compat seam for future per-topic
  streams (see `docs/scaling-and-routing.md`). Embeddings live in the
  **knowledge_vectors** `vec0` virtual table (1536-dim), keyed by `chunk_id`.
- **emails** — incoming message (`messageId`, `threadId`, sender, subject,
  body, headers, triage category) and status (`pending` / `triaged` /
  `drafted` / `needs_human` / `approved` / `sent` / `skipped` / `discarded` /
  `error`).
- **replies** — AI draft linked to an email: text, `sources_used`,
  `confidence`, `should_send`, `gmail_draft_id`, status.
- **settings** — single row: Gmail connection, reply mode (Pilot/Auto),
  confidence threshold, auto-send rules (keywords/categories).
- **sync_state** — single row: last Gmail `historyId` (opaque sync cursor).
- **credentials** — per-provider encrypted OAuth token blob (Fernet).

## UI

- **Dashboard** — email queue; each item shows sender, subject, AI draft,
  cited sources, confidence, and status, with Approve & Send / Edit & Send /
  Discard actions.
- **Knowledge Base** — upload files, paste text, view/search/delete entries.
- **Settings** — Gmail OAuth connect/disconnect, Pilot vs Auto toggle,
  confidence threshold, auto-send rules by keyword/category.

## Configuration & secrets

Required keys (keep out of source control — use a gitignored `.env`):

- **OpenAI API key** — embeddings + reply generation.
- **Google Cloud credentials** (Client ID + Client Secret) — Gmail OAuth2.

## Scope boundaries (out of scope for v1)

- No non-Gmail providers (Outlook/IMAP may come later).
- No multi-user / team accounts — single user, local deployment.
- No model fine-tuning — RAG (search + generate) only.
- No native mobile app — responsive web only.

## For AI assistants

- This document now reflects the implemented codebase, but still verify against
  actual files before relying on any claim — keep it updated as code changes.
- **Run `pytest` and `ruff check .` after changes**; tests are offline by
  design — don't introduce real network calls into them (use the fakes).
- Respect the **mail-sequential / LLM-concurrent** boundary and the **provider
  facades** (`providers`, `mail.MailProvider`, `db.vector_store.VectorStore`) —
  new providers are new classes, not edits to callers.
- This project's app calls **OpenAI** by default (not Claude); use the OpenAI
  SDK and documented model IDs unless the user changes the provider.
