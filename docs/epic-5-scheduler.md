# Epic 5 — Scheduler / Async Orchestration — Detailed Plan

Detailed plan for Epic 5: periodically pull new mail and run the RAG pipeline,
**without blocking the FastAPI app** and processing emails **concurrently**.
Builds on Epics 0–4. Ties `sync_once` (E2) → `process_email` (E4).

**Goal:** an in-process scheduler that every ~5 min runs one *cycle* —
sync new mail, then triage/retrieve/gate/generate a draft per new email —
running off the event loop, with bounded concurrency, single-flight safety, and
per-email error isolation. A manual "Sync now" trigger exposes the same cycle.

**DoD:** `run_cycle` processes all pending emails offline (fakes) with bounded
concurrency; overlapping runs are skipped (single-flight); one failing email
doesn't abort the cycle; `POST /sync/now` returns a run summary; the scheduler
starts/stops with the app lifespan.

---

## Async model (the core decisions)

The app is async (FastAPI), but our providers are **blocking**: the OpenAI SDK
(httpx, thread-safe) and Gmail (`googleapiclient` over **httplib2, NOT
thread-safe**) and `sqlite3` (sync). So "async" here means:

1. **Don't block the event loop.** Use **`AsyncIOScheduler`** (shares FastAPI's
   loop). The job is a coroutine; all blocking work is offloaded with
   `asyncio.to_thread(...)`. The web app stays responsive during a cycle.
2. **Process the slow part concurrently.** LLM calls dominate latency
   (~4–6 s/email). Run `process_email` for many emails concurrently via
   `asyncio.gather` bounded by a **`Semaphore(max_concurrency)`**, so a cycle
   with 50 emails finishes in ~1 min instead of ~5.
3. **Respect thread-safety boundaries** (this is why the Epic 4 split pays off):
   - **Gmail calls run sequentially** (httplib2 isn't thread-safe) — and they're
     fast. Only `sync_once` + per-email thread-context fetches touch Gmail.
   - **`process_email` runs concurrently** — by design it's *mail-agnostic*
     (thread context passed in as text). It only touches OpenAI (thread-safe)
     + SQLite, so it parallelizes safely.
4. **SQLite under concurrency.** Each concurrent worker opens its **own
   short-lived connection** via `connect(db_path)` (never sharing one
   connection across threads). WAL mode (already set) allows one writer +
   readers; add `PRAGMA busy_timeout` so brief write contention waits instead of
   raising "database is locked". Bounded concurrency keeps contention low.

### Cycle shape
```
run_cycle():                                  [coroutine, single-flight]
  └─ to_thread: sync_once(conn, mail)         # E2: fetch new mail → emails(pending)
  ├─ load pending emails (status='pending')
  ├─ SEQUENTIAL (httplib2-safe, fast):
  │    for each pending email:
  │      guard = check_guards(email)          # pure, no I/O
  │      if guard: persist skip               # drop bulk before any Gmail/LLM work
  │      else: thread_text = mail.get_thread(email.thread_id) → render
  └─ CONCURRENT (Semaphore, own conn each):
       for each survivor:
         to_thread: process_email(conn2, store, llm, email, thread_text=...)
  → summary {synced, drafted, needs_human, skipped, errors}
```

> Running `check_guards` up front means bulk mail is skipped **before** spending
> a Gmail thread-fetch or any LLM tokens on it. `process_email` re-checks guards
> harmlessly (returns `None` for survivors), so it stays self-contained.

---

## Proposed layout
```
app/scheduler/
├── __init__.py
├── runner.py      # run_cycle(...) — the async orchestration above
└── service.py     # AsyncIOScheduler: build, register interval job, start/stop
app/routers/sync.py # POST /sync/now (manual trigger) + GET /sync/status
```

## New dependency
`apscheduler` (`AsyncIOScheduler` from `apscheduler.schedulers.asyncio`).

## New config (`app/config.py` + `.env.example`)
| Field               | Default | Notes                                            |
| ------------------- | ------- | ------------------------------------------------ |
| `scheduler_enabled` | `true`  | start the interval job at boot (off in tests/CLI)|
| `max_concurrency`   | `4`     | concurrent `process_email` workers per cycle     |
| `sync_interval_min` | `5` (exists) | interval between cycles                      |

## Connection-safety change (`app/db/connection.py`)
- Add `PRAGMA busy_timeout = 5000` in `connect()` so concurrent writers wait.
- The scheduler/workers open their **own** connections from `settings.db_path`
  (a small `connection_factory`), independent of the request connection
  (`app.state.db`). WAL lets these coexist.

---

## Task breakdown

### 5.0 (P0) Dependency + config
Add `apscheduler`; add `scheduler_enabled`, `max_concurrency`. **Acceptance:**
config loads; defaults present.

### 5.1 (P0) Connection safety
`busy_timeout` pragma + a `connection_factory(db_path)` helper the runner uses to
open per-task connections. **Acceptance:** two connections can write the same DB
without "database is locked" under bounded concurrency (test with threads).

### 5.2 (P0) `run_cycle` orchestration (`runner.py`)
Implements the cycle above. Signature is **dependency-injected** for testability:
```python
async def run_cycle(
    *, db_path, mail_provider, llm_provider, settings, lock=None
) -> dict
```
- `sync_once` and each `process_email` run via `asyncio.to_thread`.
- Gmail thread fetch + guard-skips are sequential; `process_email` calls are
  gathered under a `Semaphore(settings.max_concurrency)`.
- Returns a summary dict (counts per outcome + error count).
**Acceptance:** with `FakeMailProvider` + a stub LLM + seeded retrieval, all
pending emails reach a terminal status; summary counts are correct.

### 5.3 (P0) Single-flight
Module-level `asyncio.Lock`; `run_cycle` returns `{"status": "skipped"}` if a run
is already in progress (non-blocking try-acquire). The APScheduler job is also
registered with `max_instances=1, coalesce=True`. **Acceptance:** a second
`run_cycle` invoked while the first holds the lock is skipped, not run twice.

### 5.4 (P0) Scheduler service (`service.py`) + lifespan
- Build `AsyncIOScheduler`; add an interval job (`minutes=sync_interval_min`,
  `max_instances=1`, `coalesce=True`) whose callback builds the live providers
  (mail via `get_mail_provider`, llm via `get_provider`) and `await run_cycle`.
- Start in FastAPI `lifespan` startup (if `scheduler_enabled`), shut down on
  exit. **Acceptance:** app boots with the scheduler started; shuts down cleanly;
  disabled when `scheduler_enabled=false`.

### 5.5 (P1) Manual trigger route (`routers/sync.py`)
- `POST /sync/now` → `await run_cycle(...)` → return summary (for the E6 UI's
  "Sync now" + tests). `GET /sync/status` → last-run summary + whether running.
- **Acceptance:** route returns a summary; respects single-flight.

### 5.6 (P0) Error isolation
Each `process_email` worker is wrapped: on exception, log it, set the email
`status='error'` (excluded from future cycles; re-queueable later via E6), and
continue. A failing email never aborts the cycle. **Acceptance:** one worker
raising still lets the others complete; the failed email is marked `error`.

### 5.7 (P1) Tests (async)
- `run_cycle`: processes pending → drafted/needs_human/skipped; single-flight
  skip; error isolation; concurrency correctness (all processed) with
  `max_concurrency>1`.
- A **content-aware stub LLM** (returns triage vs generation JSON based on the
  system prompt) so concurrent ordering is deterministic; seed/monkeypatch
  retrieval for the confident path.
- `POST /sync/now` via `TestClient`.
- Uses `pytest-asyncio` (already configured `asyncio_mode=auto`).

---

## Risks / decisions
- **httplib2 not thread-safe** → Gmail work is sequential; only the OpenAI+DB
  `process_email` is concurrent. This is safe *because* Epic 4 made the pipeline
  mail-agnostic. (If Gmail concurrency is ever needed: build one provider per
  worker.)
- **SQLite write contention** → WAL + `busy_timeout` + short transactions +
  bounded concurrency. If it ever bites, lower `max_concurrency` or move to
  Postgres (already designed behind the repo layer).
- **Poison emails** → marked `status='error'` rather than retried forever; a
  manual re-queue lands in Epic 6. (Transient vs permanent error distinction is
  a later refinement.)
- **Thread-fetch waste** → mitigated by running guards before fetching thread
  context, so bulk mail costs no Gmail/LLM work.
- **AsyncIOScheduler vs BackgroundScheduler** → AsyncIO chosen to share the
  FastAPI loop and keep one offload path (`to_thread`); no extra thread pool to
  manage beyond the default executor.

## Definition of done checklist (Epic 5)
- [ ] `apscheduler` dep + `scheduler_enabled` / `max_concurrency` config.
- [ ] `connect()` sets `busy_timeout`; per-task connection factory.
- [ ] `run_cycle`: sync → guard/skip → sequential thread-fetch → concurrent
  `process_email`; returns a summary.
- [ ] Single-flight (asyncio.Lock + `max_instances=1`).
- [ ] AsyncIOScheduler started/stopped in lifespan; disabled when configured off.
- [ ] `POST /sync/now` + `GET /sync/status`.
- [ ] Per-email error isolation (`status='error'`, logged).
- [ ] `pytest` green offline (async cycle tests + route).
