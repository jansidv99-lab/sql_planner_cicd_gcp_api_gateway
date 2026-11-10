"""Shared test setup: no test may ever reach the real LLM."""

import pytest


@pytest.fixture(autouse=True)
def _block_real_llm(monkeypatch):
    """Fail any test that tries to build the real OpenAI client.

    Tests that need an LLM pass a fake (`llm=` or `client=`), so this never triggers for them.
    """

    def _blocked(*_args, **_kwargs):
        pytest.fail("Tests must not call the real LLM; pass a fake llm/client instead")

    monkeypatch.setattr("app.llm.get_client", _blocked)
