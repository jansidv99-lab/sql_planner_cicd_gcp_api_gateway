"""Structured logging for the gateway (same approach as app/observability.py, own copy).

StructuredLogHandler writes one JSON line per record to stdout; Cloud Run turns it into a
structured Cloud Logging entry. It needs no credentials, so it works the same locally.

Privacy: never log request/response bodies, prompts, completions, keys or query strings.
Tracing (OpenTelemetry) is added in phase G13.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import TextIO

from google.cloud.logging.handlers import StructuredLogHandler

GATEWAY_LOGGER = "gateway"

# Set by RequestIdMiddleware for the duration of a request.
request_id_var: ContextVar[str | None] = ContextVar("gateway_request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Adds the current request ID to every record as a structured field."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = request_id_var.get()
        if request_id is not None:
            fields = dict(getattr(record, "json_fields", None) or {})
            fields.setdefault("request_id", request_id)
            record.json_fields = fields
        return True


def setup_logging(level: str = "INFO", stream: TextIO | None = None) -> logging.Logger:
    """Attach the structured handler to the `gateway` logger once (idempotent)."""
    logger = logging.getLogger(GATEWAY_LOGGER)
    if not any(getattr(h, "_gateway", False) for h in logger.handlers):
        handler = StructuredLogHandler(stream=stream or sys.stdout)
        handler.addFilter(RequestIdFilter())
        handler._gateway = True  # marker for idempotency
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(level)
    return logger
