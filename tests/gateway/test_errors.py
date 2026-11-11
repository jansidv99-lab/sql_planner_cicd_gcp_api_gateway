from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from gateway.errors import GatewayError, InvalidRequestError, NotFoundError


def _assert_error(response, status, error_type, code):
    assert response.status_code == status
    error = response.json()["error"]
    assert error["type"] == error_type
    assert error["code"] == code
    assert error["request_id"] == response.headers["x-request-id"]
    return error


def test_unknown_route_is_openai_shaped_404(client):
    _assert_error(client.get("/nope"), 404, "invalid_request_error", "not_found")


def test_method_not_allowed(client):
    _assert_error(client.post("/healthz"), 405, "invalid_request_error", "method_not_allowed")


def test_other_http_errors(app):
    @app.get("/teapot")
    async def teapot():
        raise HTTPException(status_code=418)

    with TestClient(app) as client:
        _assert_error(client.get("/teapot"), 418, "invalid_request_error", "http_error")


def test_gateway_errors_use_their_status_type_and_code(app):
    @app.get("/bad")
    async def bad():
        raise InvalidRequestError("Field 'x' is not supported", code="unsupported_parameter")

    @app.get("/missing")
    async def missing():
        raise NotFoundError("Unknown model alias 'x'", code="model_not_found")

    @app.get("/base")
    async def base():
        raise GatewayError("Something expected failed")

    with TestClient(app) as client:
        error = _assert_error(
            client.get("/bad"), 400, "invalid_request_error", "unsupported_parameter"
        )
        assert error["message"] == "Field 'x' is not supported"
        _assert_error(client.get("/missing"), 404, "invalid_request_error", "model_not_found")
        _assert_error(client.get("/base"), 500, "server_error", "internal_error")


def test_validation_error_hides_details(app):
    class Body(BaseModel):
        count: int

    @app.post("/echo")
    async def echo(body: Body):
        return body

    with TestClient(app) as client:
        response = client.post("/echo", json={"count": "secret-user-text"})
    error = _assert_error(response, 400, "invalid_request_error", "invalid_body")
    assert error["message"] == "Invalid request body"
    assert "secret-user-text" not in response.text


def test_unhandled_exception_is_500_without_its_message(app, logs):
    @app.get("/boom")
    async def boom():
        raise RuntimeError("prompt text that must never leak")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    error = _assert_error(response, 500, "server_error", "internal_error")
    assert error["message"] == "Internal gateway error"
    assert "must never leak" not in response.text
    assert "must never leak" not in logs.raw()
    unhandled = [line for line in logs() if line["message"] == "unhandled error"]
    assert unhandled[0]["error_type"] == "RuntimeError"
    assert unhandled[0]["request_id"] == response.headers["x-request-id"]
