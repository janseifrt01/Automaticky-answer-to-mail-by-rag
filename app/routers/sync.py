"""Manual sync trigger + status routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.scheduler import runner, service

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/now")
async def sync_now(request: Request) -> dict:
    """Run one processing cycle now (respects single-flight)."""
    return await service.run_once(request.app)


@router.get("/status")
def sync_status(request: Request) -> dict:
    """Last run summary + whether a cycle is currently running."""
    return {
        "running": runner.is_running(),
        "last_run": getattr(request.app.state, "last_run", None),
    }
