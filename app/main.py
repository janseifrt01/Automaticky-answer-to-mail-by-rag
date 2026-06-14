"""FastAPI application factory and startup wiring.

On startup the database is opened (with ``sqlite-vec``) and the schema is
bootstrapped. The connection is stored on ``app.state`` for handlers to use.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db.connection import connect
from app.db.schema import bootstrap
from app.routers import auth, health, knowledge


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the DB and bootstrap the schema for the app's lifetime."""
    settings = get_settings()
    conn = connect(settings.db_path)
    bootstrap(conn)
    app.state.db = conn
    try:
        yield
    finally:
        conn.close()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(title="RAG Mail Auto-Reply", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(knowledge.router)
    return app


app = create_app()
