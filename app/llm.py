"""The only place the app talks to the LLM (OpenAI-compatible Chat Completions API)."""

from __future__ import annotations

import functools
from collections.abc import Callable

import openai

from app.config import Settings, load_settings

LLMFn = Callable[[str, str], str]
"""Any function taking (system_prompt, user_prompt) and returning the reply text."""

TIMEOUT_SECONDS = 30
MAX_RETRIES = 2  # SDK network-level retries only (connection errors, 429, 5xx)


class LLMError(RuntimeError):
    """A user-friendly LLM failure; the original SDK error is kept as __cause__."""


@functools.lru_cache(maxsize=1)
def get_client(settings: Settings) -> openai.OpenAI:
    return openai.OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
    )


def _friendly_message(err: openai.OpenAIError) -> str:
    # Order matters: APITimeoutError is a subclass of APIConnectionError.
    if isinstance(err, openai.AuthenticationError):
        return "LLM authentication failed: check OPENAI_API_KEY"
    if isinstance(err, openai.RateLimitError):
        return "LLM rate limit reached: try again shortly"
    if isinstance(err, openai.APITimeoutError):
        return "LLM request timed out"
    if isinstance(err, openai.APIConnectionError):
        return "Could not reach the LLM endpoint: check OPENAI_BASE_URL"
    if isinstance(err, openai.NotFoundError):
        return "Model not found: check MODEL"
    return "LLM request failed"


def complete(
    system: str,
    user: str,
    *,
    settings: Settings | None = None,
    client: openai.OpenAI | None = None,
) -> str:
    """Send a system + user prompt and return the reply text (stripped)."""
    settings = settings or load_settings()
    client = client or get_client(settings)

    try:
        response = client.chat.completions.create(
            model=settings.model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    except openai.OpenAIError as err:
        raise LLMError(_friendly_message(err)) from err

    content = response.choices[0].message.content if response.choices else None
    if not content or not content.strip():
        raise LLMError("The model returned an empty response")
    return content.strip()


if __name__ == "__main__":
    # Manual smoke check: one tiny real API call using your .env settings.
    s = load_settings()
    print(f"model={s.model} base_url={s.openai_base_url}")
    print("reply:", complete("You are a test endpoint.", "Reply with the single word: OK", settings=s))
