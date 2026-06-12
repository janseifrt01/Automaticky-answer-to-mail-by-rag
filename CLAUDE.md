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

> **The repository is currently empty — no source code exists yet.**
> The sections below describe the *agreed design*, not implemented reality.
> Update this document as code lands so it reflects the actual codebase
> (directory layout, real install/run/test commands, key modules, data flow).

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

## Planned stack (Python, local single-user)

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
- **HTMX frontend**: live-ish queue + approve/edit/send actions with no
  separate JS build, which fits a single-user review dashboard.

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

## Planned data model (SQLite)

- **knowledge_chunks** — chunked KB content + embedding + source file/metadata.
- **emails** — incoming message (`messageId`, `threadId`, sender, subject,
  body, headers, triage category) and status
  (pending / drafted / approved / sent / skipped).
- **replies** — AI draft linked to an email: text, `sources_used`,
  `confidence`, `should_send`, Gmail draft id.
- **settings** — Gmail connection, reply mode (Pilot/Auto), confidence
  threshold, auto-send rules (keywords/categories).
- **sync_state** — last Gmail `historyId` for incremental sync.

## Planned UI

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

- This document reflects the agreed design, not implementation. Verify against
  actual files before relying on any claim here.
- Once real structure exists, replace the planned sections with concrete
  documentation: directory layout, how to install/run/test, key modules, and
  the end-to-end data flow.
- This project's app calls **OpenAI** by default (not Claude); use the OpenAI
  SDK and documented model IDs unless the user changes the provider.
