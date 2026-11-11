import asyncio
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from gateway.middleware import RequestIdMiddleware, resolve_request_id
from gateway.observability import GATEWAY_LOGGER, setup_logging


def test_generates_request_id(client):
    request_id = client.get("/healthz").headers["x-request-id"]
    assert len(request_id) == 32 and request_id.isalnum()


def test_echoes_valid_incoming_request_id(client):
    response = client.get("/healthz", headers={"X-Request-ID": "trace-abc_1.2"})
    assert response.headers["x-request-id"] == "trace-abc_1.2"


@pytest.mark.parametrize("bad", ["has space", "a" * 129, "semi;colon", ""])
def test_replaces_unsafe_request_id(bad):
    assert resolve_request_id(bad) != bad
    assert len(resolve_request_id(bad)) == 32


def test_each_request_gets_its_own_id(client):
    ids = {client.get("/healthz").headers["x-request-id"] for _ in range(3)}
    assert len(ids) == 3


def test_access_log_line_has_fields_but_no_query_string(app, logs):
    with TestClient(app) as client:
        response = client.get("/healthz?api_key=secret-in-query")

    access = [line for line in logs() if line["message"] == "request"]
    assert len(access) == 1
    line = access[0]
    assert line["method"] == "GET"
    assert line["path"] == "/healthz"
    assert line["status"] == 200
    assert line["duration_ms"] >= 0
    assert line["request_id"] == response.headers["x-request-id"]
    assert "secret-in-query" not in logs.raw()


def test_access_log_status_for_errors(app, logs):
    with TestClient(app) as client:
        client.get("/nope")
    assert [line["status"] for line in logs() if line["message"] == "request"] == [404]


def test_logs_written_during_a_request_carry_its_id(app, logs):
    @app.get("/work")
    async def work():
        logging.getLogger(GATEWAY_LOGGER).info("doing work")
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/work")
    work_line = next(line for line in logs() if line["message"] == "doing work")
    assert work_line["request_id"] == response.headers["x-request-id"]


def test_logs_outside_requests_have_no_request_id(logs):
    logging.getLogger(GATEWAY_LOGGER).info("startup")
    assert "request_id" not in logs()[0]


def test_setup_logging_is_idempotent(logs):
    setup_logging("INFO")
    setup_logging("DEBUG")
    logger = logging.getLogger(GATEWAY_LOGGER)
    assert sum(getattr(h, "_gateway", False) for h in logger.handlers) == 1
    assert logger.level == logging.DEBUG


def test_error_after_response_started_is_re_raised(app):
    async def body():
        yield b"partial"
        raise RuntimeError("mid-stream failure")

    @app.get("/stream")
    async def stream():
        return StreamingResponse(body())

    with TestClient(app) as client, pytest.raises(RuntimeError, match="mid-stream"):
        client.get("/stream")


def test_non_http_scopes_pass_through():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(RequestIdMiddleware(inner)({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]
