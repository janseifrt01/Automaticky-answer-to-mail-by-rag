"""Async, non-blocking processing cycle.

One ``run_cycle`` does: sync new mail (E2) → drop bulk via guards → fetch thread
context (sequential, httplib2-safe) → process survivors concurrently (E4,
bounded). Blocking work is offloaded with ``asyncio.to_thread``; each concurrent
worker uses its own SQLite connection. Sending is Epic 7 — this produces drafts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import Settings
from app.db.connection import connect
from app.db.repositories import emails as emails_repo
from app.db.repositories import settings as settings_repo
from app.db.vector_store import SqliteVecStore
from app.mail import sender
from app.mail.base import MailProvider
from app.mail.ingest import sync_once
from app.providers.base import Provider
from app.rag.guards import check_guards
from app.rag.pipeline import process_email

logger = logging.getLogger(__name__)

# Single-flight across the scheduled job and the manual trigger.
_lock = asyncio.Lock()

_PENDING_LIMIT = 1000


def is_running() -> bool:
    """Whether a cycle is currently in progress."""
    return _lock.locked()


def _render_thread(messages: list[Any]) -> str:
    """Render thread messages (domain EmailMessage) to a context block."""
    return "\n\n".join(
        f"From: {m.sender}\n{m.body_text}" for m in messages
    )


def _sync(db_path: str, mail_provider: MailProvider) -> int:
    conn = connect(db_path)
    try:
        return sync_once(conn, mail_provider)
    finally:
        conn.close()


def _process_one(
    db_path: str,
    llm: Provider,
    email: dict[str, Any],
    thread_text: str,
    settings: Settings,
) -> dict:
    """Run the pipeline for one email on its own connection; isolate errors."""
    conn = connect(db_path)
    try:
        store = SqliteVecStore(conn)
        return process_email(
            conn, store, llm, email, thread_text=thread_text, settings=settings
        )
    except Exception:  # noqa: BLE001 - isolate one bad email from the cycle
        logger.exception("process_email failed for email id=%s", email.get("id"))
        try:
            emails_repo.update_status(conn, email["id"], "error")
        except Exception:  # noqa: BLE001
            logger.exception("failed marking email id=%s as error", email.get("id"))
        return {"status": "error"}
    finally:
        conn.close()


async def run_cycle(
    *,
    db_path: str,
    mail_provider: MailProvider,
    llm_provider: Provider,
    settings: Settings,
    lock: asyncio.Lock | None = None,
) -> dict:
    """Run one processing cycle. Skipped (no-op) if one is already running."""
    lock = lock or _lock
    if lock.locked():
        return {"status": "skipped", "reason": "already running"}
    async with lock:
        return await _run(db_path, mail_provider, llm_provider, settings)


async def _run(
    db_path: str,
    mail_provider: MailProvider,
    llm_provider: Provider,
    settings: Settings,
) -> dict:
    summary = {
        "status": "ok",
        "synced": 0,
        "drafted": 0,
        "needs_human": 0,
        "skipped": 0,
        "sent": 0,
        "errors": 0,
    }

    # 1. Sync new mail (blocking → thread).
    summary["synced"] = await asyncio.to_thread(_sync, db_path, mail_provider)

    # 2. Guard-skip + sequential thread-context fetch (httplib2-safe).
    survivors: list[tuple[dict[str, Any], str]] = []
    conn = connect(db_path)
    try:
        pending = emails_repo.list_emails(conn, status="pending", limit=_PENDING_LIMIT)
        account_email = settings_repo.get_settings_row(conn).get("gmail_email")
        for email in pending:
            guard = check_guards(email, account_email=account_email)
            if guard is not None:
                emails_repo.set_triage(
                    conn, email["id"], guard.category, status="skipped"
                )
                summary["skipped"] += 1
                continue
            thread_text = ""
            thread_id = email.get("thread_id")
            if thread_id:
                try:
                    thread_text = _render_thread(mail_provider.get_thread(thread_id))
                except Exception:  # noqa: BLE001 - thread context is best-effort
                    logger.exception("get_thread failed for %s", thread_id)
            survivors.append((email, thread_text))
    finally:
        conn.close()

    # 3. Process survivors concurrently (OpenAI + DB; own connection each).
    semaphore = asyncio.Semaphore(settings.max_concurrency)

    async def _worker(email: dict[str, Any], thread_text: str) -> dict:
        async with semaphore:
            return await asyncio.to_thread(
                _process_one, db_path, llm_provider, email, thread_text, settings
            )

    results = await asyncio.gather(*(_worker(e, t) for e, t in survivors))
    for result in results:
        status = result.get("status")
        if status == "drafted":
            summary["drafted"] += 1
        elif status == "needs_human":
            summary["needs_human"] += 1
        elif status == "skipped":
            summary["skipped"] += 1
        elif status == "error":
            summary["errors"] += 1

    # 4. Sequential dispatch (Epic 7): Pilot Gmail drafts vs gated Auto-send.
    await asyncio.to_thread(
        _dispatch_drafts, db_path, mail_provider, survivors, results, settings, summary
    )
    return summary


def _dispatch_drafts(
    db_path: str,
    mail_provider: MailProvider,
    survivors: list[tuple[dict[str, Any], str]],
    results: list[dict],
    settings: Settings,
    summary: dict,
) -> None:
    """Create Pilot drafts / auto-send freshly drafted replies (sequential)."""
    if not mail_provider.is_connected():
        return
    conn = connect(db_path)
    try:
        settings_row = settings_repo.get_settings_row(conn)
        for (email, _), result in zip(survivors, results, strict=True):
            if result.get("status") != "drafted":
                continue
            try:
                action = sender.dispatch(
                    conn, mail_provider, email["id"], settings_row,
                    create_drafts=settings.create_gmail_drafts,
                )
            except Exception:  # noqa: BLE001 - isolate a bad send from the rest
                logger.exception("dispatch failed for email %s", email["id"])
                continue
            if action == "sent":
                summary["drafted"] -= 1
                summary["sent"] += 1
    finally:
        conn.close()
