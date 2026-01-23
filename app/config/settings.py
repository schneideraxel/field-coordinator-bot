# app/config/settings.py
# Typed environment settings (fail-fast)
# AS 🐚🫧🪼🪸
# 12.08.2025 (Last update)

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_required(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


@dataclass(frozen=True)
class Settings:
    """Configuration for the GitHub automation worker.
    Minimal and stdlib-only.
    """
    # --- GitHub App ---
    app_id: str = field(default_factory=lambda: _env_required("GITHUB_APP_ID"))
    installation_id: str = field(default_factory=lambda: _env_required("GITHUB_INSTALLATION_ID"))
    private_key: str = field(default_factory=lambda: _env_required("GITHUB_PRIVATE_KEY"))  # PEM or base64-PEM

    # --- HTTP / Retry ---
    http_timeout_s: int = int(os.getenv("HTTP_TIMEOUT", "15"))
    http_retries: int = int(os.getenv("HTTP_RETRIES", "5"))
    user_agent: str = os.getenv("HTTP_USER_AGENT", "gh-automation/1.0")

    # --- Concurrency ---
    max_inflight: int = int(os.getenv("MAX_INFLIGHT", "8"))

    # --- Logging ---
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Endpoints (GHES overrides) ---
    api_base_url: str = os.getenv("GITHUB_API_BASE", "https://api.github.com")
    graphql_url: str = os.getenv("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")

