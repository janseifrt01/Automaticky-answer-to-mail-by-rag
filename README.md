# RAG Mail Auto-Reply

A single-user email assistant that reads a Gmail inbox, retrieves relevant
context from a user-provided knowledge base, and drafts replies using AI
(Retrieval-Augmented Generation). Runs locally for one user / one inbox.

> **Status:** early development. Epic 0 (foundations) is implemented — app
> skeleton, config, SQLite + `sqlite-vec` schema, provider abstraction, tests.
> See `BACKLOG.md` and `docs/` for the roadmap and per-epic plans, and
> `CLAUDE.md` for the design.

## Requirements

- Python 3.11+
- An OpenAI API key (embeddings + reply generation)
- Google Cloud OAuth credentials (Gmail) — needed from Epic 2 onward

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime + dev/test deps
```

## Configure

```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY (and Google credentials later)
```

Configuration keys are documented in `.env.example` and typed in
`app/config.py`.

## Run

```bash
uvicorn app.main:app --reload
```

The app opens the SQLite database (creating `./data/app.db`), loads
`sqlite-vec`, and bootstraps the schema on startup. Check it's alive:

```bash
curl http://127.0.0.1:8000/health      # -> {"status":"ok"}
```

## Test

```bash
pytest
```

Tests run fully offline (no OpenAI/Gmail network calls).

## Project layout

```
app/
  config.py            # pydantic-settings configuration
  main.py              # FastAPI app factory + startup bootstrap
  db/                  # connection (sqlite-vec) + schema bootstrap
  providers/           # embed()/generate() interface + OpenAI impl
  routers/             # HTTP routes (health, ...)
tests/                 # pytest suite + offline fixtures
docs/                  # per-epic implementation plans
```
