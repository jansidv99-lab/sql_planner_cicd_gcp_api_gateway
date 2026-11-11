"""App factory: wires settings, lifespan resources, middleware, error handlers and routes.

Run locally:  uvicorn --factory gateway.main:create_app --port 8081 --no-access-log
No side effects at import; a missing or invalid setting raises ConfigError and stops startup.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI

from gateway.api import health
from gateway.config import GatewaySettings, load_gateway_settings
from gateway.errors import install_error_handlers
from gateway.middleware import RequestIdMiddleware
from gateway.observability import setup_logging


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    settings = settings or load_gateway_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # One connection pool for all upstream calls (timeouts are configured in phase G2).
        async with httpx2.AsyncClient() as http:
            app.state.http = http
            yield
        app.state.http = None

    # /docs, /redoc and /openapi.json are not part of the contract: keep the surface minimal.
    app = FastAPI(
        title="LLM Gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = settings
    app.state.http = None

    install_error_handlers(app)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    return app
