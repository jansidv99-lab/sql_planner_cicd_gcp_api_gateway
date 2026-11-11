"""Liveness and readiness probes (no auth; used by Cloud Run from phase G4)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from gateway.errors import ServiceUnavailableError

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up and answering."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    """Readiness: settings are loaded and the shared HTTP client is open."""
    http = getattr(request.app.state, "http", None)
    if getattr(request.app.state, "settings", None) is None or http is None or http.is_closed:
        raise ServiceUnavailableError("Gateway is not ready")
    return {"status": "ready"}
