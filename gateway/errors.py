"""OpenAI-shaped error responses (docs/gateway/03_api_contract.md §5).

Services raise GatewayError subclasses; the handlers registered by `install_error_handlers`
turn every failure, including unknown routes and unexpected exceptions, into
`{"error": {"message", "type", "code", "request_id"}}`. Messages never contain prompt text,
keys or exception messages.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from gateway.observability import GATEWAY_LOGGER, request_id_var

logger = logging.getLogger(GATEWAY_LOGGER)


class GatewayError(Exception):
    """An expected failure with a fixed HTTP status, OpenAI error type and code."""

    status_code = 500
    error_type = "server_error"
    code = "internal_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class InvalidRequestError(GatewayError):
    status_code = 400
    error_type = "invalid_request_error"
    code = "invalid_body"


class NotFoundError(GatewayError):
    status_code = 404
    error_type = "invalid_request_error"
    code = "not_found"


class ServiceUnavailableError(GatewayError):
    status_code = 503
    error_type = "server_error"
    code = "not_ready"


def error_response(status_code: int, error_type: str, code: str, message: str) -> JSONResponse:
    body = {
        "error": {
            "message": message,
            "type": error_type,
            "code": code,
            "request_id": request_id_var.get(),
        }
    }
    return JSONResponse(status_code=status_code, content=body)


async def _gateway_error(_request: Request, exc: GatewayError) -> JSONResponse:
    return error_response(exc.status_code, exc.error_type, exc.code, exc.message)


async def _validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    # Pydantic's details can echo request content, so only a fixed message is returned.
    return error_response(400, "invalid_request_error", "invalid_body", "Invalid request body")


async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return error_response(404, "invalid_request_error", "not_found", "Not found")
    if exc.status_code == 405:
        return error_response(
            405, "invalid_request_error", "method_not_allowed", "Method not allowed"
        )
    return error_response(exc.status_code, "invalid_request_error", "http_error", "Request failed")


def internal_error_response(exc: Exception) -> JSONResponse:
    """500 for unexpected exceptions; used by RequestIdMiddleware.

    Handled there rather than with an `Exception` handler: Starlette runs that handler in its
    outermost middleware, outside ours, so the response would lose the X-Request-ID header.
    Only the exception type is logged: its message could contain request data.
    """
    logger.error("unhandled error", extra={"json_fields": {"error_type": type(exc).__name__}})
    return error_response(500, "server_error", "internal_error", "Internal gateway error")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(GatewayError, _gateway_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
