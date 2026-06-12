# Epic 0 — Project Setup & Foundations (Detailed Plan)

Detailed, implementation-ready plan for Epic 0 of the MVP backlog
(`BACKLOG.md`). Architecture per `CLAUDE.md`: local single-user, Python,
FastAPI + SQLite/`sqlite-vec` + APScheduler, OpenAI, Gmail API.

**Goal of Epic 0:** a runnable, testable skeleton — the app starts, loads
config, opens the database with vector support, and exposes the provider
interface — with no business logic yet. Everything after this builds on it.

**Epic-level definition of done**
- `pip install -r requirements.txt` succeeds in a clean venv.
- `uvicorn app.main:app` starts; `GET /health` returns `{"status": "ok"}`.
- On startup the SQLite DB is created, `sqlite-vec` loads, and all tables exist.
- `pytest` runs green against a temporary DB with faked OpenAI/Gmail clients.
- `embed()` / `generate()` exist behind a provider interface (OpenAI impl).

---

## Proposed repository layout (created during Epic 0)

```
.
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app factory + startup hooks
│   ├── config.py            # pydantic-settings Settings
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py    # open DB, load sqlite-vec
│   │   └── schema.py        # CREATE TABLE statements + bootstrap()
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py          # EmbeddingProvider / LLMProvider protocols
│   │   └── openai_provider.py
│   └── routers/
│       ├── __init__.py
│       └── health.py        # GET /health
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # temp DB + fake-provider fixtures
│   ├── test_health.py
│   ├── test_db_bootstrap.py
│   └── test_config.py
├── .env.example
├── .gitignore
├── requirements.txt
├── pyproject.toml           # tooling config (ruff, pytest)
└── README.md
```

---

## Task 0.1 — Scaffold repo

**Deliverables**
- Directory tree above (empty `__init__.py` where needed).
- `.gitignore` covering: `.env`, `*.db`, `*.db-wal`, `*.db-shm`,
  `__pycache__/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`.
- `requirements.txt` pinned (see versions below).
- `pyproject.toml` with `ruff` + `pytest` config (line length, test paths).
- `README.md` stub with install / run / test sections.

**Proposed dependencies** (pin exact versions at implementation time)
- Runtime: `fastapi`, `uvicorn[standard]`, `pydantic-settings`,
  `sqlite-vec`, `openai`, `jinja2`, `python-multipart`.
- Dev: `pytest`, `pytest-asyncio`, `httpx` (FastAPI TestClient), `ruff`.
- (Gmail/parsing/scheduler deps land in their own epics, not here.)

**Acceptance:** clean `pip install -r requirements.txt` succeeds; `git status`
shows no `.env`/`*.db` tracked.

## Task 0.2 — Config layer (`app/config.py`)

**Deliverables** — a `Settings(BaseSettings)` model loaded from `.env`:

| Field                  | Type    | Default                    | Notes                       |
| ---------------------- | ------- | -------------------------- | --------------------------- |
| `openai_api_key`       | str     | — (required)               | embeddings + generation     |
| `google_client_id`     | str     | "" (set when Gmail lands)  | OAuth2                      |
| `google_client_secret` | str     | ""                         | OAuth2                      |
| `db_path`              | str     | `./data/app.db`            | SQLite file                 |
| `embedding_model`      | str     | `text-embedding-3-small`   | swappable                   |
| `generation_model`     | str     | `gpt-4o-mini`              | swappable                   |
| `confidence_threshold` | float   | `0.75`                     | retrieval gate              |
| `reply_mode`           | enum    | `pilot`                    | `pilot` \| `auto`           |
| `sync_interval_min`    | int     | `5`                        | scheduler interval          |

- `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`.
- `@lru_cache` `get_settings()` accessor; dependency-injectable in FastAPI.
- Fail fast with a clear error if `openai_api_key` is missing at startup.

**Acceptance:** `test_config.py` loads a fixture `.env`, asserts defaults and
overrides; missing required key raises a clear validation error.

## Task 0.3 — FastAPI skeleton (`app/main.py`, `app/routers/health.py`)

**Deliverables**
- App factory `create_app() -> FastAPI`; module-level `app = create_app()`.
- Startup hook (lifespan) → calls DB bootstrap (Task 0.4).
- `GET /health` → `{"status": "ok"}` (router in `app/routers/health.py`).
- README documents `uvicorn app.main:app --reload`.

**Acceptance:** `test_health.py` via `TestClient` gets `200` + correct body.

## Task 0.4 — SQLite bootstrap (`app/db/connection.py`, `app/db/schema.py`)

**Deliverables**
- `get_connection()` — opens SQLite at `settings.db_path` (creates parent dir),
  `enable_load_extension(True)`, loads `sqlite-vec`, sets `PRAGMA journal_mode=
  WAL` and `foreign_keys=ON`.
- `bootstrap(conn)` — idempotent `CREATE TABLE IF NOT EXISTS` for all five
  tables (full columns defined in Epic 1; create minimal-but-correct shells
  here) + the `sqlite-vec` virtual table for `knowledge_chunks` embeddings.
- Verify `sqlite-vec` loaded by querying `vec_version()`.

**Acceptance:** `test_db_bootstrap.py` — bootstrap on a temp DB, assert all
tables exist (`sqlite_master`), `vec_version()` returns a value, and a second
bootstrap call is a no-op (idempotent).

## Task 0.5 — Test harness (`tests/conftest.py`)

**Deliverables**
- `tmp_db` fixture → temp file DB, bootstrapped, yielded, torn down.
- `client` fixture → FastAPI `TestClient` wired to the temp DB via dependency
  override.
- `fake_provider` fixture → in-memory `embed()`/`generate()` returning
  deterministic vectors/text (no network, no API key needed in tests).
- `pytest.ini`/`pyproject` config so `pytest` discovers `tests/`.

**Acceptance:** `pytest` runs green offline (no real OpenAI/Gmail calls).

## Task 0.6 — Provider abstraction (`app/providers/`)

**Deliverables**
- `base.py` — `Protocol`s:
  - `EmbeddingProvider.embed(texts: list[str]) -> list[list[float]]`
  - `LLMProvider.generate(system: str, user: str, *, json_schema=None) -> str`
- `openai_provider.py` — concrete `OpenAIProvider` implementing both, reading
  model names + key from `Settings`; thin wrapper over the `openai` SDK.
- A `get_provider()` factory selecting the implementation by config (OpenAI
  default), so OpenAI ↔ Claude is a later config swap, not a rewrite.

**Acceptance:** unit test against `fake_provider` confirms the interface;
`OpenAIProvider` is import-safe without network (no calls at construction).

---

## Build order within Epic 0

1. 0.1 scaffold → 2. 0.2 config → 3. 0.4 DB bootstrap → 4. 0.3 FastAPI + health
(wires startup to bootstrap) → 5. 0.6 providers → 6. 0.5 tests last (or
test-as-you-go per task, which is preferred).

## Risks / decisions to confirm

- **`sqlite-vec` install/loadability** on the target OS — validate the wheel
  loads early (0.4); it's the one external native dependency.
- **DB access style** — plain `sqlite3` stdlib (simple, fits single-user) vs an
  ORM (SQLModel/SQLAlchemy). Plan assumes **stdlib `sqlite3`** for minimal deps;
  revisit if query complexity grows.
- **Async vs sync DB** — single-user volume is low; synchronous `sqlite3` called
  from FastAPI is acceptable for MVP (revisit only if it blocks the event loop).

## Definition of done checklist (Epic 0)

- [ ] Clean install works; lockfile/`requirements.txt` committed.
- [ ] `uvicorn app.main:app` serves `/health` → `{"status":"ok"}`.
- [ ] DB bootstraps with `sqlite-vec` loaded; all tables present; idempotent.
- [ ] `Settings` loads from `.env`; missing required key fails clearly.
- [ ] Provider interface + OpenAI impl present; swappable via config.
- [ ] `pytest` green offline; fixtures for temp DB + fake provider.
- [ ] README documents install / run / test; `.env.example` lists all keys.
