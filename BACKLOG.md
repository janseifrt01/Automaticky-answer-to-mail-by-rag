# MVP Backlog — RAG Mail Auto-Reply

Task backlog for the MVP. Scope and architecture follow `CLAUDE.md` (local,
single-user; FastAPI + SQLite/`sqlite-vec` + APScheduler; OpenAI; Gmail API).

**Legend** — Priority: P0 (MVP-critical) · P1 (needed for a good MVP) ·
P2 (nice-to-have, can slip). Status: `[ ]` todo · `[~]` in progress ·
`[x]` done.

**MVP definition of done:** connect a Gmail account, build a knowledge base
from files/text, automatically sync new mail, triage + retrieve + generate a
grounded draft (with confidence gating and safe-sender guards), review it in a
dashboard, and Approve & Send. Auto-send works only when all guards pass.

---

## Epic 0 — Project setup & foundations

- [ ] **0.1 (P0)** Scaffold repo: `app/` package, `pyproject.toml`/
  `requirements.txt`, `.gitignore` (`.env`, `*.db`, `__pycache__`), `README`.
- [ ] **0.2 (P0)** Config layer with `pydantic-settings`: load `OPENAI_API_KEY`,
  Google client id/secret, DB path, confidence threshold, reply mode from `.env`.
- [ ] **0.3 (P0)** FastAPI app skeleton: app factory, health endpoint, run via
  `uvicorn`; document `install` / `run` / `test` commands in README + CLAUDE.md.
- [ ] **0.4 (P0)** SQLite bootstrap: open DB, load `sqlite-vec` extension,
  create tables (see Epic 1), idempotent migrations on startup.
- [ ] **0.5 (P1)** Test harness: `pytest`, fixtures for a temp SQLite DB and a
  fake OpenAI/Gmail client; CI-less local `pytest` green.
- [ ] **0.6 (P1)** Provider abstraction: `embed(texts)` / `generate(prompt)`
  interface with an OpenAI implementation (keeps provider swappable).

## Epic 1 — Data model & persistence

- [ ] **1.1 (P0)** `knowledge_chunks` table — id, source_file, chunk_text,
  metadata, embedding (vector).
- [ ] **1.2 (P0)** `emails` table — messageId, threadId, sender, subject, body,
  headers, triage_category, status (pending/drafted/approved/sent/skipped),
  timestamps.
- [ ] **1.3 (P0)** `replies` table — email_id (fk), reply_text, sources_used,
  confidence, should_send, gmail_draft_id, status.
- [ ] **1.4 (P0)** `settings` table — gmail connection, reply_mode (Pilot/Auto),
  confidence_threshold, auto_send_rules (keywords/categories).
- [ ] **1.5 (P0)** `sync_state` table — last Gmail `historyId`.
- [ ] **1.6 (P1)** Repository/data-access helpers + unit tests for each table.

## Epic 2 — Mail integration (provider facade)

> Mail access sits behind a provider-agnostic **`MailProvider`** facade
> (receive + send); **Gmail/OAuth2** is the only v1 implementation, a future
> Outlook/IMAP provider is a new class. Detailed plan: `docs/epic-2-mail-facade.md`.

- [ ] **2.0 (P0)** `MailProvider` interface + provider-agnostic domain models
  (`EmailMessage`, `OutgoingMessage`, `SyncResult`); no provider types leak.
- [ ] **2.1 (P0)** Encrypted credential storage: `credentials` table +
  `TokenCipher` (Fernet); tokens encrypted at rest.
- [ ] **2.2 (P0)** Gmail OAuth2 flow: connect/callback/disconnect, minimal
  scopes (`gmail.readonly` + `gmail.compose`), auto-refresh.
- [ ] **2.3 (P0)** Gmail client wrapper: messages/threads/history/drafts with
  retry/backoff on transient errors.
- [ ] **2.4 (P0)** `GmailProvider`: implements `MailProvider`, maps Gmail API ⇄
  domain models (plaintext body, selected headers, thread order).
- [ ] **2.5 (P0)** Incremental receive via opaque cursor (Gmail `historyId`) +
  full-sync fallback when the cursor is expired.
- [ ] **2.6 (P0)** Send + create-draft with correct threading
  (`In-Reply-To` / `References` / reuse `threadId`).
- [ ] **2.7 (P0)** `get_mail_provider()` factory + config fields.
- [ ] **2.8 (P0)** `sync_once()` ingestion: fetch → idempotent upsert into the
  emails repo → persist new cursor (the unit Epic 5 schedules).
- [ ] **2.9 (P1)** Tests + reusable `FakeMailProvider` for later epics.

## Epic 3 — Knowledge base ingestion

> Write side of the retrieval seam shared with Epic 4. Detailed plan:
> `docs/epics-3-4-rag.md`.

- [ ] **3.1 (P0)** Parsers: PDF (`pypdf`), DOCX (`python-docx`), TXT (plain read).
- [ ] **3.2 (P0)** Chunking (char window + overlap), metadata retained.
- [ ] **3.3 (P0)** Ingest service: parse → chunk → embed → index via the
  Epic 1 `knowledge` repo + `VectorStore`; re-ingest replaces a source.
- [ ] **3.4 (P0)** KB routes: upload / paste / list / delete (JSON; UI in E6).
- [ ] **3.5 (P1)** Tests: parsers, chunk boundaries, ingest idempotency, delete
  removes chunks **and** vectors.

## Epic 4 — RAG pipeline (triage → retrieve → gate → generate)

> Read side of the retrieval seam; shares embedding model + scoring with Epic 3.
> Detailed plan: `docs/epics-3-4-rag.md`. Stops at a stored draft (send = E7).

- [ ] **4.0 (P0)** Shared `scoring.py`: distance↔similarity + confidence gate.
- [ ] **4.1 (P0)** Safe-sender / loop guards (rule-based on Epic 2 headers).
- [ ] **4.2 (P0)** LLM triage: answerable-from-KB / needs-human / no-reply;
  malformed output fails safe to needs-human.
- [ ] **4.3 (P0)** Retrieve: embed email (+ thread context), vector-search top-k.
- [ ] **4.4 (P0)** Confidence gate: top score < threshold → flag needs-human,
  no draft.
- [ ] **4.5 (P0)** Grounded generation: answer only from context; structured
  output `{reply, sources_used, confidence, should_send}`.
- [ ] **4.6 (P0)** Pipeline `process_email`: orchestrate + persist via existing
  repos (email status, reply + cited sources). No schema changes.
- [ ] **4.7 (P1)** Tests: guards, triage, retrieval scoring, gate, generation,
  end-to-end (mock LLM).

## Epic 5 — Scheduler / async orchestration

> Async, non-blocking cycle tying `sync_once` (E2) → `process_email` (E4).
> Detailed plan: `docs/epic-5-scheduler.md`. Sending (drafts/auto) is Epic 7;
> this epic produces drafted reply rows.

- [ ] **5.0 (P0)** `apscheduler` dep + config (`scheduler_enabled`,
  `max_concurrency`).
- [ ] **5.1 (P0)** Connection safety: `busy_timeout` + per-task connection
  factory (own connection per concurrent worker).
- [ ] **5.2 (P0)** `run_cycle`: sync → guard-skip → sequential Gmail thread
  fetch → **concurrent** `process_email` (bounded `Semaphore`), off the event
  loop via `asyncio.to_thread`.
- [ ] **5.3 (P0)** Single-flight (asyncio.Lock + APScheduler
  `max_instances=1`/`coalesce`).
- [ ] **5.4 (P0)** `AsyncIOScheduler` started/stopped in app lifespan.
- [ ] **5.5 (P1)** Manual `POST /sync/now` + `GET /sync/status`.
- [ ] **5.6 (P0)** Per-email error isolation (`status='error'`, logged).
- [ ] **5.7 (P1)** Async tests: cycle outcomes, single-flight, error isolation,
  concurrency.

## Epic 6 — Web UI (dashboard, KB, settings)

> FastAPI + Jinja2 + HTMX + Tailwind (no JS build). Design: `docs/epic-6-ui-design.md`.
> The **send** action behavior is delivered by Epic 7; E6 ships the queue,
> review/edit/approve/discard, KB management, and settings.

- [ ] **6.1 (P0)** Dashboard: email queue showing sender, subject, AI draft,
  cited sources, confidence, status.
- [ ] **6.2 (P0)** Actions: Approve & Send / Edit & Send / Discard (HTMX).
- [ ] **6.3 (P0)** Knowledge Base page: upload, paste, list/search/delete.
- [ ] **6.4 (P0)** Settings page: Gmail connect/disconnect, Pilot/Auto toggle,
  confidence threshold, auto-send rules.
- [ ] **6.5 (P1)** Responsive Tailwind styling; empty/error/loading states.

## Epic 7 — Safety, send policy & hardening

- [ ] **7.1 (P0)** Pilot mode: create native **Gmail draft**; nothing sends
  without explicit action.
- [ ] **7.2 (P0)** Gated Auto-send: send only when triage + confidence +
  safe-sender guards all pass; otherwise fall back to draft.
- [ ] **7.3 (P0)** Correct threading on send: `In-Reply-To` / `References` +
  reuse `threadId`.
- [ ] **7.4 (P1)** Encrypt OAuth tokens at rest; never log secrets.
- [ ] **7.5 (P1)** Rate-limit / cost guard on embeddings + generation calls.

## Epic 8 — Docs & developer experience

- [ ] **8.1 (P0)** README: setup, Google Cloud OAuth app steps, OpenAI key,
  run/test commands.
- [ ] **8.2 (P0)** Update `CLAUDE.md` as real structure lands (replace "planned"
  sections with actual layout, commands, modules, data flow).
- [ ] **8.3 (P1)** `.env.example` with all required keys documented.

---

## Suggested build order (vertical slices)

1. **Epics 0 + 1** — skeleton, config, DB schema.
2. **Epic 2 (read-only)** — OAuth + incremental sync; confirm emails land in DB.
3. **Epic 3** — knowledge base ingest + indexing.
4. **Epic 4** — triage → gate → grounded generation (drafts stored, not sent).
5. **Epic 6** — dashboard + KB + settings UI to review drafts.
6. **Epics 5 + 7** — scheduler automation, Gmail drafts, gated Auto-send.
7. **Epic 8** — docs polish.

## Out of scope for MVP

Non-Gmail providers, multi-user/teams, model fine-tuning, native mobile app,
Gmail push (Pub/Sub) notifications, analytics/reporting.
