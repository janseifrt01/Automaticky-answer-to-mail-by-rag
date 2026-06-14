# RAG Mail Auto-Reply

A single-user email assistant that reads a Gmail inbox, retrieves relevant
context from a knowledge base you provide, and drafts replies using AI
(Retrieval-Augmented Generation: search the knowledge base, then generate).
Runs **locally for one user / one inbox**.

- **Pilot mode (default):** every draft is reviewed before sending.
- **Auto mode:** sends automatically, but only when triage + confidence +
  safe-sender guards all pass.

> **Status:** MVP complete (Epics 0–7). End-to-end: scheduled inbox sync →
> triage → retrieve → confidence gate → grounded draft → review/edit → send.
> See `CLAUDE.md` for architecture, `BACKLOG.md` for the roadmap, and `docs/`
> for per-epic design notes.

## How it works

1. **Connect Gmail** via OAuth2 (minimal scopes).
2. **Build a knowledge base** — upload PDF/DOCX/TXT or paste text; it's chunked,
   embedded, and indexed in SQLite (`sqlite-vec`).
3. **Sync** — a scheduler pulls new mail (~every 5 min) using the Gmail History
   API; processed messages are idempotent.
4. **Triage** — classify each email (answerable / needs-human / no-reply) and
   skip automated senders & lists via safe-sender guards.
5. **Retrieve + gate** — vector-search the KB; if the top score is below the
   confidence threshold, flag for a human instead of guessing.
6. **Generate** — draft a reply grounded only in retrieved context, with cited
   sources and a confidence score.
7. **Review & send** — Pilot: approve/edit/discard in the dashboard. Auto: send
   when all gates pass.

## Requirements

- Python 3.11+
- An **OpenAI API key** (embeddings + reply generation)
- **Google Cloud OAuth credentials** (Gmail) — see setup below

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime + dev/test deps
```

## Configure

```bash
cp .env.example .env
```

Edit `.env` (all keys are documented there and typed in `app/config.py`). The
essentials:

- `OPENAI_API_KEY` — required.
- `TOKEN_ENCRYPTION_KEY` — required to connect a mailbox (encrypts stored OAuth
  tokens). Generate one with:
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — from the Google Cloud setup.

### Google Cloud / Gmail OAuth setup

1. In the [Google Cloud Console](https://console.cloud.google.com/), create (or
   pick) a project.
2. **APIs & Services → Library →** enable the **Gmail API**.
3. **APIs & Services → OAuth consent screen →** configure (External is fine for
   a personal app), and add your Gmail address as a **Test user**.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID →**
   application type **Web application**. Add an **Authorized redirect URI**:
   `http://localhost:8000/auth/gmail/callback`
   (must match `GOOGLE_REDIRECT_URI` in `.env`).
5. Copy the **Client ID** and **Client secret** into `.env`.

Scopes requested are minimal: `gmail.readonly` (read messages + history) and
`gmail.compose` (create drafts + send). OAuth tokens are stored **encrypted at
rest**.

## Run

```bash
uvicorn app.main:app --reload
```

On startup the app opens the SQLite database (creating `./data/app.db`), loads
`sqlite-vec`, bootstraps the schema, and starts the background sync scheduler.
Check it's alive:

```bash
curl http://127.0.0.1:8000/health      # -> {"status":"ok"}
```

Open the web UI at <http://127.0.0.1:8000/>.

### First use

1. **Settings →** Connect Gmail (completes the OAuth flow).
2. **Knowledge Base →** upload files or paste text to build the KB.
3. **Dashboard →** click **Sync now** (or wait for the scheduler). New emails
   are triaged, drafted, and shown in the queue.
4. Review each draft → **Approve & Send**, **Edit**, or **Discard**. Switch to
   **Auto** mode in Settings once you trust it.

## Test

```bash
pytest          # full suite, fully offline (no OpenAI/Gmail network calls)
ruff check .    # lint
```

## Project layout

```
app/
  main.py              # FastAPI app factory + lifespan (DB + scheduler)
  config.py            # pydantic-settings configuration
  deps.py              # FastAPI dependencies (db, providers, mail)
  db/
    connection.py      # SQLite + sqlite-vec connection
    schema.py          # schema + idempotent bootstrap
    repositories/      # data access per table
    vector_store/      # VectorStore interface + sqlite-vec impl
  providers/           # embed()/generate() interface + OpenAI impl
  mail/                # MailProvider facade, Gmail impl, sender, ingest
  rag/                 # chunking, ingest, triage, retrieval, generate, pipeline
  scheduler/           # async run_cycle + APScheduler service
  routers/             # health, auth, knowledge, sync, web (HTML/HTMX)
  templates/           # Jinja2 + HTMX UI
tests/                 # pytest suite + offline fixtures (fakes)
docs/                  # per-epic design notes
```

## Architecture notes

The app is built on three swappable facades so the big choices stay as config,
not rewrites:

- **`providers`** (`embed()` / `generate()`) — OpenAI today; Claude is a swap.
- **`mail.MailProvider`** — Gmail/OAuth2 today; Outlook/IMAP is a new class.
- **`db.vector_store.VectorStore`** — `sqlite-vec` today; pgvector later.

Knowledge chunks carry a `namespace` (default `"default"`) as a seam for future
per-topic streams. See `docs/scaling-and-routing.md`.
