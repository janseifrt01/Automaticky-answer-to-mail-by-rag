"""Web UI: server-rendered pages + HTMX fragment endpoints.

Renders the dashboard (review queue), knowledge base, and settings using Jinja2
+ HTMX. Action endpoints return the smallest changed fragment. The actual Gmail
send behind "Approve & Send" lands in Epic 7; here approve marks the reply
approved and queues it.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db.repositories import emails as emails_repo
from app.db.repositories import knowledge as kb_repo
from app.db.repositories import replies as replies_repo
from app.db.repositories import settings as settings_repo
from app.db.schema import vector_table_dim
from app.db.vector_store import SqliteVecStore
from app.deps import get_db, get_embedder, get_mail, get_vector_store
from app.mail import sender
from app.mail.base import MailProvider
from app.providers.base import Provider
from app.providers.factory import expected_embedding_dim
from app.rag import ingest, parsers, reindex
from app.scheduler import runner, service

logger = logging.getLogger(__name__)

TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)

router = APIRouter(tags=["web"])

# Tabs shown on the dashboard (label, status filter).
QUEUE_FILTERS = [
    ("All", None),
    ("Drafted", "drafted"),
    ("Needs human", "needs_human"),
    ("Skipped", "skipped"),
    ("Sent", "sent"),
]


def _render(request: Request, name: str, **ctx) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, name, ctx)


def _card_context(
    conn: sqlite3.Connection, email_id: int, *, edit: bool = False
) -> dict:
    email = emails_repo.get_email(conn, email_id)
    if email is None:
        raise HTTPException(status_code=404, detail="email not found")
    reply = replies_repo.get_latest_for_email(conn, email_id)
    return {"email": email, "reply": reply, "edit": edit}


def _status_context(request: Request, conn: sqlite3.Connection) -> dict:
    return {
        "settings": settings_repo.get_settings_row(conn),
        "last_run": getattr(request.app.state, "last_run", None),
        "running": runner.is_running(),
    }


# --- Dashboard ---------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    return _render(
        request,
        "dashboard.html",
        filters=QUEUE_FILTERS,
        active="all",
        cards=_queue(conn, None),
        **_status_context(request, conn),
    )


@router.get("/emails", response_class=HTMLResponse)
def email_list(
    request: Request,
    status: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
):
    return _render(
        request,
        "partials/email_list.html",
        cards=_queue(conn, status),
    )


def _queue(conn: sqlite3.Connection, status: str | None) -> list[dict]:
    status = None if status in (None, "", "all") else status
    rows = emails_repo.list_emails(conn, status=status, limit=200)
    return [
        {"email": e, "reply": replies_repo.get_latest_for_email(conn, e["id"])}
        for e in rows
    ]


@router.get("/emails/{email_id}", response_class=HTMLResponse)
def email_card(
    request: Request, email_id: int, conn: sqlite3.Connection = Depends(get_db)
):
    return _render(request, "partials/email_card.html", **_card_context(conn, email_id))


@router.get("/emails/{email_id}/edit", response_class=HTMLResponse)
def email_edit(
    request: Request, email_id: int, conn: sqlite3.Connection = Depends(get_db)
):
    return _render(
        request, "partials/email_card.html", **_card_context(conn, email_id, edit=True)
    )


@router.post("/emails/{email_id}/reply", response_class=HTMLResponse)
def save_reply(
    request: Request,
    email_id: int,
    reply_text: str = Form(...),
    conn: sqlite3.Connection = Depends(get_db),
):
    reply = replies_repo.get_latest_for_email(conn, email_id)
    if reply is None:
        raise HTTPException(status_code=404, detail="no reply to edit")
    replies_repo.update_reply(conn, reply["id"], reply_text=reply_text)
    return _render(request, "partials/email_card.html", **_card_context(conn, email_id))


@router.post("/emails/{email_id}/approve", response_class=HTMLResponse)
def approve(
    request: Request,
    email_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    mail: MailProvider = Depends(get_mail),
):
    """Approve & Send: send the current reply via the mail provider."""
    email = emails_repo.get_email(conn, email_id)
    reply = replies_repo.get_latest_for_email(conn, email_id)
    if email is None or reply is None:
        raise HTTPException(status_code=404, detail="email or reply not found")
    if not mail.is_connected():
        ctx = _card_context(conn, email_id)
        return _render(
            request, "partials/email_card.html", error="Gmail not connected", **ctx
        )
    try:
        sender.send_reply(conn, mail, email, reply)
    except Exception:  # noqa: BLE001 - surface send failures in the UI
        logger.exception("send failed for email %s", email_id)
        ctx = _card_context(conn, email_id)
        return _render(
            request, "partials/email_card.html", error="Send failed", **ctx
        )
    return _render(request, "partials/email_card.html", **_card_context(conn, email_id))


@router.post("/emails/{email_id}/discard", response_class=HTMLResponse)
def discard(
    request: Request, email_id: int, conn: sqlite3.Connection = Depends(get_db)
):
    reply = replies_repo.get_latest_for_email(conn, email_id)
    if reply is not None:
        replies_repo.update_reply(conn, reply["id"], status="discarded")
    emails_repo.update_status(conn, email_id, "discarded")
    return _render(request, "partials/email_card.html", **_card_context(conn, email_id))


@router.post("/emails/{email_id}/requeue", response_class=HTMLResponse)
def requeue(
    request: Request, email_id: int, conn: sqlite3.Connection = Depends(get_db)
):
    emails_repo.update_status(conn, email_id, "pending")
    return _render(request, "partials/email_card.html", **_card_context(conn, email_id))


# --- Knowledge base ----------------------------------------------------------

@router.get("/knowledge", response_class=HTMLResponse)
def knowledge_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    row = settings_repo.get_settings_row(conn)
    return _render(
        request,
        "knowledge.html",
        sources=kb_repo.list_sources(conn),
        index_dim=vector_table_dim(conn),
        expected_dim=expected_embedding_dim(row),
        **_status_context(request, conn),
    )


def _kb_fragment(request: Request, conn, *, message=None, error=None) -> HTMLResponse:
    return _render(
        request,
        "partials/kb_sources.html",
        sources=kb_repo.list_sources(conn),
        message=message,
        error=error,
    )


@router.post("/knowledge/upload", response_class=HTMLResponse)
async def kb_upload(
    request: Request,
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_db),
    store: SqliteVecStore = Depends(get_vector_store),
    provider: Provider = Depends(get_embedder),
):
    data = await file.read()
    cfg = get_settings()
    try:
        text = parsers.extract_text(file.filename or "", data)
    except parsers.UnsupportedFileType as exc:
        return _kb_fragment(request, conn, error=str(exc))
    count = ingest.ingest_text(
        conn, store, provider,
        source_type="file", source_name=file.filename or "upload", text=text,
        chunk_size=cfg.chunk_size, chunk_overlap=cfg.chunk_overlap,
    )
    return _kb_fragment(
        request, conn, message=f"Added {file.filename} ({count} chunks)"
    )


@router.post("/knowledge/paste", response_class=HTMLResponse)
def kb_paste(
    request: Request,
    label: str = Form(...),
    text: str = Form(...),
    conn: sqlite3.Connection = Depends(get_db),
    store: SqliteVecStore = Depends(get_vector_store),
    provider: Provider = Depends(get_embedder),
):
    cfg = get_settings()
    count = ingest.ingest_text(
        conn, store, provider,
        source_type="paste", source_name=label, text=text,
        chunk_size=cfg.chunk_size, chunk_overlap=cfg.chunk_overlap,
    )
    return _kb_fragment(request, conn, message=f"Added {label} ({count} chunks)")


@router.post("/knowledge/{source_name}/delete", response_class=HTMLResponse)
def kb_delete(
    request: Request,
    source_name: str,
    conn: sqlite3.Connection = Depends(get_db),
    store: SqliteVecStore = Depends(get_vector_store),
):
    removed = kb_repo.delete_by_source(conn, store, source_name)
    return _kb_fragment(
        request, conn, message=f"Deleted {source_name} ({removed} chunks)"
    )


@router.post("/knowledge/reindex", response_class=HTMLResponse)
def kb_reindex(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
    store: SqliteVecStore = Depends(get_vector_store),
    provider: Provider = Depends(get_embedder),
):
    try:
        count, dim = reindex.reindex_all(conn, store, provider)
    except Exception as exc:  # noqa: BLE001 - surface model/download errors in the UI
        return _kb_fragment(request, conn, error=f"Reindex failed: {exc}")
    return _kb_fragment(
        request, conn, message=f"Reindexed {count} chunks at {dim}-dim"
    )


# --- Settings ----------------------------------------------------------------

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    return _render(
        request,
        "settings.html",
        settings=settings_repo.get_settings_row(conn),
        last_run=getattr(request.app.state, "last_run", None),
        running=runner.is_running(),
    )


@router.post("/settings", response_class=HTMLResponse)
def settings_save(
    request: Request,
    reply_mode: str = Form("pilot"),
    confidence_threshold: float = Form(0.75),
    auto_send_keywords: str = Form(""),
    llm_provider: str = Form("openai"),
    embedding_provider: str = Form("openai"),
    generation_model: str = Form(""),
    conn: sqlite3.Connection = Depends(get_db),
):
    keywords = [k.strip() for k in auto_send_keywords.split(",") if k.strip()]
    settings_repo.update_settings(
        conn,
        reply_mode=reply_mode,
        confidence_threshold=confidence_threshold,
        auto_send_rules={"keywords": keywords},
        llm_provider=llm_provider,
        embedding_provider=embedding_provider,
        generation_model=generation_model.strip(),
    )
    return _render(
        request,
        "partials/settings_form.html",
        settings=settings_repo.get_settings_row(conn),
        saved=True,
    )


# --- Sync action -------------------------------------------------------------

@router.post("/actions/sync", response_class=HTMLResponse)
async def action_sync(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    await service.run_once(request.app)
    return _render(
        request, "partials/status_bar.html", **_status_context(request, conn)
    )


@router.get("/partials/status-bar", response_class=HTMLResponse)
def status_bar(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    return _render(
        request, "partials/status_bar.html", **_status_context(request, conn)
    )
