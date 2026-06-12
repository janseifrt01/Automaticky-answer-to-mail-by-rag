# CLAUDE.md

Guidance for AI assistants (Claude Code) working in this repository.

## Project

**RAG Mail Auto-Reply** — an intelligent email assistant that reads a Gmail
inbox, retrieves relevant context from a user-provided knowledge base, and
automatically drafts (or sends) replies using AI (Retrieval-Augmented
Generation: search the knowledge base, then generate).

Single-user per deployment. Web app only (fully responsive). Starts in
**Pilot mode** (every draft is reviewed before sending) and can switch to
**Auto mode** (send immediately) for specific categories/keywords.

## Status

> **The repository is currently empty — no source code exists yet.**
> The sections below describe the *planned* design, not implemented reality.
> Update this document as code lands so it reflects the actual codebase
> (directory layout, real install/run/test commands, key modules, data flow).

## How it works

1. **Connect Gmail** — link a Gmail account via Google OAuth2.
2. **Build a knowledge base** — upload PDF/DOCX/TXT or paste text; content is
   chunked, embedded, and indexed.
3. **Poll inbox** — a cron job checks for new, unanswered emails every ~5 min.
4. **Draft a reply** — embed the incoming email, vector-search the knowledge
   base for relevant chunks, generate a reply with the LLM.
5. **Review & send** — in Pilot mode the user approves / edits / discards each
   draft; in Auto mode matching emails are sent automatically.

## Planned stack (Python)

The solution is built in **Python**. The original idea sketched a Convex/JS
stack; the Convex-specific pieces (serverless functions, built-in vector
search, cron) are replaced with Python-native equivalents below.

| Layer                 | Technology                                                        |
| --------------------- | ---------------------------------------------------------------- |
| Backend / API         | **FastAPI** (async, OpenAPI built-in)                            |
| Database              | **PostgreSQL**                                                    |
| Vector search         | **pgvector** (Postgres extension — vectors live next to data)    |
| Inbox polling         | **APScheduler** every ~5 min (or Celery + Redis for a worker)    |
| AI embeddings         | OpenAI `text-embedding-3-small` (provider-swappable)             |
| AI reply generation   | OpenAI `gpt-4o-mini` (provider-swappable)                        |
| Email integration     | Gmail API — `google-api-python-client` + `google-auth-oauthlib` |
| File parsing          | `pypdf` (PDF), `python-docx` (DOCX), plain read (TXT)           |
| Frontend              | FastAPI + Jinja2 + HTMX + Tailwind (or a React SPA)              |
| Config / secrets      | `.env` + `pydantic-settings`; OAuth tokens encrypted in DB       |

**Design notes / decisions:**

- **Postgres + pgvector** instead of a separate vector DB: a single-user app
  doesn't need a dedicated vector service — keep emails, knowledge chunks, and
  embeddings in one transactional store.
- **HTMX over React**: the review dashboard works well with server-rendered
  HTMX (live-ish queue, approve/edit/send) and no separate JS build. Choose
  React only for a richer client.
- **Polling over push**: APScheduler polling matches the original 5-minute
  plan and is simplest; Gmail push via Pub/Sub watch is a later optimization.
- **Provider stays pluggable**: keep one `embed()` / `generate()` interface so
  OpenAI ↔ Claude is a config swap, not a rewrite. OpenAI is the documented
  default unless the user changes it.

## Planned data model (Postgres)

- **knowledge chunks** — chunked + embedded knowledge-base content.
- **emails** — incoming messages with status (pending / approved / sent).
- **replies** — AI-drafted replies linked to emails.
- **settings** — Gmail connection, reply mode (Pilot/Auto), auto-send rules.

## Planned UI

- **Dashboard** — email queue; each item shows sender, subject, AI draft, and
  status, with Approve & Send / Edit & Send / Discard actions.
- **Knowledge Base** — upload files, paste text, view/search/delete entries.
- **Settings** — Gmail OAuth connect/disconnect, Pilot vs Auto toggle,
  auto-send rules by keyword/category.

## Configuration & secrets

Required keys (keep out of source control — use a gitignored `.env`):

- **OpenAI API key** — embeddings + reply generation.
- **Google Cloud credentials** (Client ID + Client Secret) — Gmail OAuth2.

## Scope boundaries (explicitly out of scope for v1)

- No non-Gmail providers (Outlook/IMAP may come later).
- No multi-user / team accounts — single user per deployment.
- No model fine-tuning — RAG (search + generate) only.
- No native mobile app — responsive web only.

## For AI assistants

- This document reflects intent, not implementation. Verify against actual
  files before relying on any claim here.
- Once real structure exists, replace the planned sections with concrete
  documentation: directory layout, how to install/run/test, key modules, and
  the end-to-end data flow.
