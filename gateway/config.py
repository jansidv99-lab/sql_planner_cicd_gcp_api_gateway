"""Gateway settings from the environment (GATEWAY_* variables), validated once at startup.

Fail fast: every problem is reported in one ConfigError, and the app factory lets it stop the
process, so an instance with bad config never receives traffic.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

REQUIRED_VARS = (
    "GATEWAY_PROVIDER_BASE_URL",
    "GATEWAY_PROVIDER_API_KEY",
    "GATEWAY_DEFAULT_MODEL",
)
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LOCAL_HOSTS = ("localhost", "127.0.0.1")


class ConfigError(RuntimeError):
    """Raised when gateway settings are missing or invalid."""


@dataclass(frozen=True)
class GatewaySettings:
    provider_base_url: str
    provider_api_key: str
    default_model: str
    log_level: str = "INFO"

    def __repr__(self) -> str:  # keep the provider key out of logs and tracebacks
        return (
            f"GatewaySettings(provider_base_url={self.provider_base_url!r}, "
            f"default_model={self.default_model!r}, log_level={self.log_level!r})"
        )


def _url_problem(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.hostname:
        return None
    if parsed.scheme == "http" and parsed.hostname in LOCAL_HOSTS:
        return None  # local fake provider in tests and demos
    return "GATEWAY_PROVIDER_BASE_URL must be an https:// URL (http:// only for localhost)"


def load_gateway_settings(env: Mapping[str, str] | None = None) -> GatewaySettings:
    """Read settings from `env`, or from `.env` + the process environment when `env` is None.

    `.env` never overrides variables that are already set (e.g. on Cloud Run).
    """
    if env is None:
        load_dotenv(override=False)
        env = os.environ

    values = {name: (env.get(name) or "").strip() for name in REQUIRED_VARS}
    log_level = (env.get("GATEWAY_LOG_LEVEL") or "INFO").strip().upper()

    problems = [f"{name} is missing" for name, value in values.items() if not value]
    if values["GATEWAY_PROVIDER_BASE_URL"]:
        problem = _url_problem(values["GATEWAY_PROVIDER_BASE_URL"])
        if problem:
            problems.append(problem)
    if log_level not in LOG_LEVELS:
        problems.append(f"GATEWAY_LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}")
    if problems:
        raise ConfigError("Invalid gateway settings: " + "; ".join(problems))

    return GatewaySettings(
        provider_base_url=values["GATEWAY_PROVIDER_BASE_URL"].rstrip("/"),
        provider_api_key=values["GATEWAY_PROVIDER_API_KEY"],
        default_model=values["GATEWAY_DEFAULT_MODEL"],
        log_level=log_level,
    )
