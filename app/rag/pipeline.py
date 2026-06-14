"""Pipeline orchestration: guards → triage → retrieve → gate → generate.

Produces a stored draft reply (or a status flag) for one email. Stays
mail-agnostic: thread context is fetched by the caller (Epic 5 scheduler) via
``MailProvider.get_thread`` and passed in as text. Sending is Epic 7.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.config import Settings, get_settings
from app.db.repositories import emails as emails_repo
from app.db.repositories import replies as replies_repo
from app.db.repositories import settings as settings_repo
from app.db.vector_store.base import VectorStore
from app.providers.base import Provider
from app.rag.generate import generate_reply
from app.rag.guards import check_guards
from app.rag.retrieval import retrieve
from app.rag.scoring import passes_gate
from app.rag.triage import TriageCategory, classify

# Email status values produced by the pipeline.
STATUS_SKIPPED = "skipped"
STATUS_NEEDS_HUMAN = "needs_human"
STATUS_DRAFTED = "drafted"


def _result(status: str, category: str, reason: str, reply_id: int | None) -> dict:
    return {
        "status": status,
        "category": category,
        "reason": reason,
        "reply_id": reply_id,
    }


def process_email(
    conn: sqlite3.Connection,
    store: VectorStore,
    provider: Provider,
    email: dict[str, Any],
    *,
    thread_text: str = "",
    settings: Settings | None = None,
) -> dict:
    """Run the RAG pipeline for one email row; persist outcome. Returns a summary."""
    settings = settings or get_settings()
    email_id = email["id"]
    config_row = settings_repo.get_settings_row(conn)
    threshold = config_row.get("confidence_threshold", settings.confidence_threshold)
    account_email = config_row.get("gmail_email")

    # 1. Safe-sender / loop guards (cheap, no LLM).
    guard = check_guards(email, account_email=account_email)
    if guard is not None:
        emails_repo.set_triage(conn, email_id, guard.category, status=STATUS_SKIPPED)
        return _result(STATUS_SKIPPED, guard.category, guard.reason, None)

    # 2. LLM triage.
    triage = classify(provider, email)
    if triage.category == TriageCategory.NO_REPLY.value:
        emails_repo.set_triage(conn, email_id, triage.category, status=STATUS_SKIPPED)
        return _result(STATUS_SKIPPED, triage.category, triage.reason, None)
    if triage.category == TriageCategory.NEEDS_HUMAN.value:
        emails_repo.set_triage(
            conn, email_id, triage.category, status=STATUS_NEEDS_HUMAN
        )
        return _result(STATUS_NEEDS_HUMAN, triage.category, triage.reason, None)

    # 3. Retrieve + 4. confidence gate.
    query = f"{email.get('subject', '')}\n\n{email.get('body_text', '')}"
    chunks = retrieve(conn, store, provider, query, settings.retrieval_top_k)
    answerable = TriageCategory.ANSWERABLE.value
    if not chunks or not passes_gate(chunks[0].score, threshold):
        emails_repo.set_triage(conn, email_id, answerable, status=STATUS_NEEDS_HUMAN)
        return _result(
            STATUS_NEEDS_HUMAN, answerable, "no confident KB answer", None
        )

    # 5. Grounded generation.
    result = generate_reply(provider, email, chunks, thread_text=thread_text)
    if not result.reply:
        emails_repo.set_triage(conn, email_id, answerable, status=STATUS_NEEDS_HUMAN)
        return _result(
            STATUS_NEEDS_HUMAN, answerable, "generation produced no reply", None
        )

    reply_id = replies_repo.create_reply(
        conn,
        email_id=email_id,
        reply_text=result.reply,
        sources_used=result.sources_used,
        confidence=result.confidence,
        should_send=result.should_send,
    )
    emails_repo.set_triage(conn, email_id, answerable, status=STATUS_DRAFTED)
    return _result(STATUS_DRAFTED, answerable, triage.reason, reply_id)
