import pytest

from app.config import ConfigError, Settings, load_settings

FULL_ENV = {
    "OPENAI_API_KEY": "sk-secret-value",
    "OPENAI_BASE_URL": "https://example.test/v1",
    "MODEL": "test-model",
}


def test_all_present_returns_settings():
    assert load_settings(FULL_ENV) == Settings(
        openai_api_key="sk-secret-value",
        openai_base_url="https://example.test/v1",
        model="test-model",
    )


def test_one_missing_is_named():
    env = {k: v for k, v in FULL_ENV.items() if k != "MODEL"}
    with pytest.raises(ConfigError, match="MODEL"):
        load_settings(env)


def test_several_missing_named_in_one_message():
    with pytest.raises(ConfigError) as exc:
        load_settings({"OPENAI_BASE_URL": "https://example.test/v1"})
    assert "OPENAI_API_KEY" in str(exc.value)
    assert "MODEL" in str(exc.value)


def test_blank_value_counts_as_missing():
    with pytest.raises(ConfigError, match="MODEL"):
        load_settings({**FULL_ENV, "MODEL": "   "})


def test_secret_not_in_error_message():
    with pytest.raises(ConfigError) as exc:
        load_settings({**FULL_ENV, "MODEL": ""})
    assert "sk-secret-value" not in str(exc.value)


def test_secret_not_in_repr():
    assert "sk-secret-value" not in repr(load_settings(FULL_ENV))
