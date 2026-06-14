"""Knowledge-base management routes: upload / paste / list / delete.

Returns JSON; the Epic 6 UI builds on these. Embedding is done through the
injected provider, so tests can stay offline by overriding ``get_embedder``.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import get_settings
from app.db.repositories import knowledge as kb_repo
from app.db.vector_store import SqliteVecStore
from app.deps import get_db, get_embedder, get_vector_store
from app.providers.base import Provider
from app.rag import ingest, parsers

router = APIRouter(prefix="/kb", tags=["knowledge"])


class PasteRequest(BaseModel):
    text: str
    label: str
    namespace: str = "default"


def _ingest(conn, store, provider, *, source_type, source_name, text, namespace):
    settings = get_settings()
    return ingest.ingest_text(
        conn,
        store,
        provider,
        source_type=source_type,
        source_name=source_name,
        text=text,
        namespace=namespace,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    namespace: str = Form("default"),
    conn: sqlite3.Connection = Depends(get_db),
    store: SqliteVecStore = Depends(get_vector_store),
    provider: Provider = Depends(get_embedder),
) -> dict:
    data = await file.read()
    try:
        text = parsers.extract_text(file.filename or "", data)
    except parsers.UnsupportedFileType as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    count = _ingest(
        conn,
        store,
        provider,
        source_type="file",
        source_name=file.filename or "upload",
        text=text,
        namespace=namespace,
    )
    return {"source_name": file.filename, "namespace": namespace, "chunks": count}


@router.post("/paste")
def paste(
    body: PasteRequest,
    conn: sqlite3.Connection = Depends(get_db),
    store: SqliteVecStore = Depends(get_vector_store),
    provider: Provider = Depends(get_embedder),
) -> dict:
    count = _ingest(
        conn,
        store,
        provider,
        source_type="paste",
        source_name=body.label,
        text=body.text,
        namespace=body.namespace,
    )
    return {"source_name": body.label, "namespace": body.namespace, "chunks": count}


@router.get("")
def list_sources(
    namespace: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    return {"sources": kb_repo.list_sources(conn, namespace=namespace)}


@router.delete("/{source_name}")
def delete(
    source_name: str,
    namespace: str = "default",
    conn: sqlite3.Connection = Depends(get_db),
    store: SqliteVecStore = Depends(get_vector_store),
) -> dict:
    removed = kb_repo.delete_by_source(conn, store, source_name, namespace=namespace)
    return {"source_name": source_name, "namespace": namespace, "deleted": removed}
