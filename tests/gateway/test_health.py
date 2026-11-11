import pytest
from fastapi.testclient import TestClient

from gateway.config import ConfigError
from gateway.main import create_app


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_when_lifespan_running(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_503_before_startup(app):
    # Without the context manager the lifespan doesn't run, so no HTTP client exists.
    response = TestClient(app).get("/readyz")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "not_ready"


def test_http_client_closed_after_shutdown(app):
    with TestClient(app):
        http = app.state.http
        assert not http.is_closed
    assert http.is_closed
    assert app.state.http is None


def test_docs_endpoints_disabled(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_create_app_fails_fast_without_settings(monkeypatch):
    monkeypatch.setattr("gateway.config.load_dotenv", lambda **_kwargs: None)
    for name in ("GATEWAY_PROVIDER_BASE_URL", "GATEWAY_PROVIDER_API_KEY", "GATEWAY_DEFAULT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigError):
        create_app()
