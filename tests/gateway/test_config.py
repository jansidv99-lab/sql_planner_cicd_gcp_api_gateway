import pytest

from gateway import config
from gateway.config import ConfigError, load_gateway_settings

VALID = {
    "GATEWAY_PROVIDER_BASE_URL": "https://provider.example.com/v1/",
    "GATEWAY_PROVIDER_API_KEY": "sk-secret-value",
    "GATEWAY_DEFAULT_MODEL": "gpt-test",
}


def test_valid_settings_with_defaults():
    s = load_gateway_settings(VALID)
    assert s.provider_base_url == "https://provider.example.com/v1"  # trailing slash removed
    assert s.provider_api_key == "sk-secret-value"
    assert s.default_model == "gpt-test"
    assert s.log_level == "INFO"


def test_log_level_is_normalized():
    assert load_gateway_settings({**VALID, "GATEWAY_LOG_LEVEL": " debug "}).log_level == "DEBUG"


@pytest.mark.parametrize("missing", list(VALID))
def test_each_required_var(missing):
    env = {**VALID, missing: "  "}
    with pytest.raises(ConfigError, match=f"{missing} is missing"):
        load_gateway_settings(env)


def test_all_problems_reported_together():
    with pytest.raises(ConfigError) as err:
        load_gateway_settings({"GATEWAY_LOG_LEVEL": "loud"})
    message = str(err.value)
    for name in VALID:
        assert f"{name} is missing" in message
    assert "GATEWAY_LOG_LEVEL must be one of" in message


@pytest.mark.parametrize(
    "url",
    ["http://provider.example.com/v1", "ftp://provider.example.com", "provider.example.com"],
)
def test_rejects_insecure_or_invalid_urls(url):
    with pytest.raises(ConfigError, match="must be an https:// URL"):
        load_gateway_settings({**VALID, "GATEWAY_PROVIDER_BASE_URL": url})


@pytest.mark.parametrize("url", ["http://localhost:9999/v1", "http://127.0.0.1:8000"])
def test_allows_http_for_localhost(url):
    assert load_gateway_settings({**VALID, "GATEWAY_PROVIDER_BASE_URL": url})


def test_key_not_in_repr():
    s = load_gateway_settings(VALID)
    assert "sk-secret-value" not in repr(s)
    assert "provider.example.com" in repr(s)


def test_reads_process_environment_when_no_env_given(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda **_kwargs: None)  # ignore a local .env
    for name, value in VALID.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("GATEWAY_LOG_LEVEL", raising=False)
    assert load_gateway_settings().default_model == "gpt-test"
