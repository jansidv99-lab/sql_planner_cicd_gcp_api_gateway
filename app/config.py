"""Load settings (OPENAI_API_KEY, OPENAI_BASE_URL, MODEL) from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

REQUIRED_VARS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "MODEL")


class ConfigError(RuntimeError):
    """Raised when required settings are missing."""


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_base_url: str
    model: str

    def __repr__(self) -> str:  # keep the API key out of logs and tracebacks
        return f"Settings(openai_base_url={self.openai_base_url!r}, model={self.model!r})"


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read settings from `env`, or from `.env` + the process environment when `env` is None.

    `.env` never overrides variables that are already set (e.g. on Cloud Run).
    """
    if env is None:
        load_dotenv(override=False)
        env = os.environ

    values = {name: (env.get(name) or "").strip() for name in REQUIRED_VARS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigError(f"Missing required settings: {', '.join(missing)}")

    return Settings(
        openai_api_key=values["OPENAI_API_KEY"],
        openai_base_url=values["OPENAI_BASE_URL"],
        model=values["MODEL"],
    )
