"""Request-ID middleware and the per-request access log line.

Pure ASGI (not BaseHTTPMiddleware) so it also works for streamed responses (phase G10).
"""

from __future__ import annotations

import logging
import re
import uuid
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gateway.errors import internal_error_response
from gateway.observability import GATEWAY_LOGGER, request_id_var

REQUEST_ID_HEADER = "x-request-id"
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")

logger = logging.getLogger(GATEWAY_LOGGER)


def resolve_request_id(incoming: str | None) -> str:
    """Use the caller's ID if it's safe to echo and log, otherwise generate one."""
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        request_id = resolve_request_id(headers.get(REQUEST_ID_HEADER))
        token = request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500  # if the app fails before sending a response
        started = False
        start = perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                status, started = message["status"], True
                message.setdefault("headers", [])
                message["headers"] = [
                    *[(k, v) for k, v in message["headers"] if k.lower() != b"x-request-id"],
                    (REQUEST_ID_HEADER.encode(), request_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            if started:  # headers already sent (e.g. mid-stream): nothing safe to send
                raise
            await internal_error_response(exc)(scope, receive, send_with_id)
        finally:
            # Path only: the query string could carry data.
            logger.info(
                "request",
                extra={
                    "json_fields": {
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "duration_ms": round((perf_counter() - start) * 1000, 1),
                    }
                },
            )
            request_id_var.reset(token)
