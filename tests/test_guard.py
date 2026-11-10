import pytest

from app.config import Settings
from app.llm import complete


def test_real_llm_is_blocked_in_tests():
    settings = Settings("sk-test", "https://example.test/v1", "test-model")
    with pytest.raises(pytest.fail.Exception, match="must not call the real LLM"):
        complete("system", "user", settings=settings)
