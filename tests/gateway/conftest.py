"""Gateway test setup: fake settings, an in-process client, captured logs, no network."""

from __future__ import annotations

import io
import json
import logging

import httpx2
import pytest
from fastapi.testclient import TestClient

from gateway.config import GatewaySettings
from gateway.main import create_app
from gateway.observability import GATEWAY_LOGGER, setup_logging

FAKE_KEY = "sk-fake-provider-key-0123456789"


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """Fail any gateway test that would open a real upstream connection.

    Tests that need an upstream use httpx2.MockTransport (phase G2), which bypasses this.
    """

    async def _blocked(*_args, **_kwargs):
        pytest.fail("Gateway tests must not reach the network; use httpx2.MockTransport")

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", _blocked)


@pytest.fixture(autouse=True)
def _reset_gateway_logger():
    yield
    logger = logging.getLogger(GATEWAY_LOGGER)
    for handler in [h for h in logger.handlers if getattr(h, "_gateway", False)]:
        logger.removeHandler(handler)
    logger.propagate = True
    logger.setLevel(logging.NOTSET)


@pytest.fixture
def settings() -> GatewaySettings:
    return GatewaySettings(
        provider_base_url="http://localhost:9999/v1",
        provider_api_key=FAKE_KEY,
        default_model="fake-model",
    )


@pytest.fixture
def logs():
    """Capture gateway log lines as dicts (installed before the app, which then reuses it)."""
    stream = io.StringIO()
    setup_logging("INFO", stream=stream)

    def read() -> list[dict]:
        return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]

    read.raw = stream.getvalue  # full text, for "must not appear anywhere" checks
    return read


@pytest.fixture
def app(settings, logs):
    # Depends on `logs` so the capture handler is installed first (setup_logging reuses it).
    return create_app(settings)


@pytest.fixture
def client(app):
    """TestClient with lifespan running (shared HTTP client open)."""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
