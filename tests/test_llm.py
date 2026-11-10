from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.config import Settings
from app.llm import MAX_RETRIES, TIMEOUT_SECONDS, LLMError, complete
from app.llm import get_client as real_get_client  # captured before the test guard

SETTINGS = Settings(
    openai_api_key="sk-secret-value",
    openai_base_url="https://example.test/v1",
    model="test-model",
)

_REQUEST = httpx2.Request("POST", "https://example.test/v1/chat/completions")


def _status_error(cls, code):
    return cls("boom", response=httpx2.Response(code, request=_REQUEST), body=None)


class FakeClient:
    """Mimics client.chat.completions.create; records the call, returns or raises."""

    def __init__(self, content="SELECT 1", error=None):
        self.calls = []
        self._content = content
        self._error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_returns_content_stripped():
    client = FakeClient(content="  hello \n")
    assert complete("sys", "usr", settings=SETTINGS, client=client) == "hello"


def test_sends_model_temperature_and_messages():
    client = FakeClient()
    complete("the system", "the user", settings=SETTINGS, client=client)
    (call,) = client.calls
    assert call["model"] == "test-model"
    assert call["temperature"] == 0
    assert call["messages"] == [
        {"role": "system", "content": "the system"},
        {"role": "user", "content": "the user"},
    ]


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_content_raises(content):
    with pytest.raises(LLMError, match="empty response"):
        complete("s", "u", settings=SETTINGS, client=FakeClient(content=content))


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_status_error(openai.AuthenticationError, 401), "check OPENAI_API_KEY"),
        (_status_error(openai.RateLimitError, 429), "rate limit"),
        (openai.APITimeoutError(request=_REQUEST), "timed out"),
        (openai.APIConnectionError(request=_REQUEST), "check OPENAI_BASE_URL"),
        (_status_error(openai.NotFoundError, 404), "check MODEL"),
        (_status_error(openai.InternalServerError, 500), "LLM request failed"),
    ],
)
def test_sdk_errors_mapped(error, expected):
    with pytest.raises(LLMError, match=expected) as exc:
        complete("s", "u", settings=SETTINGS, client=FakeClient(error=error))
    assert exc.value.__cause__ is error
    assert "sk-secret-value" not in str(exc.value)


def test_get_client_builds_configured_client():
    real_get_client.cache_clear()
    client = real_get_client(SETTINGS)
    assert str(client.base_url).rstrip("/") == "https://example.test/v1"
    assert client.max_retries == MAX_RETRIES
    assert client.timeout == TIMEOUT_SECONDS
    assert real_get_client(SETTINGS) is client  # cached
