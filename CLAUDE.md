# CLAUDE.md

Guidance for AI assistants (Claude Code) working in this repository.

## Project

**Automaticky-answer-to-mail-by-rag** — a system that automatically drafts
replies to incoming email using Retrieval-Augmented Generation (RAG): relevant
context is retrieved from a knowledge base and passed to an LLM to generate the
reply.

## Status

> **The repository is currently empty — no source code exists yet.**
> This file is a minimal stub. The sections below describe the *intended*
> direction, not implemented reality. Update this document as soon as real
> code, structure, and workflows land so it reflects the actual codebase.

## Intended stack

- **Language:** Python
- **LLM:** Claude via the Anthropic SDK (`anthropic`). Default to the latest
  capable models (e.g. Opus / Sonnet 4.x) for generation; a smaller/faster
  model is fine for lightweight retrieval or classification steps.
- **Retrieval:** a vector store + embeddings over the email knowledge base.
- **Mail I/O:** IMAP/SMTP or the Gmail API for reading incoming mail and
  sending drafts.

## Conventions (to confirm once code exists)

- Keep secrets (API keys, mail credentials) out of source — use environment
  variables or a local `.env` that is gitignored.
- Document setup, run, and test commands here once they exist.

## For AI assistants

- This stub reflects intent, not implementation. Before relying on any claim
  here, verify against the actual files in the repo.
- When real structure is added, replace this stub with concrete documentation:
  directory layout, how to install/run/test, key modules, and data flow.
