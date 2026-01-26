# app/adapters/github/auth.py
# GitHub App auth: JWT + installation access token cache
# AS 🐚🫧🪼🪸
# 17.01.2025 (Last update)

from __future__ import annotations

import base64
import os
import time
from typing import Optional
from pathlib import Path
import httpx
import jwt

from app.core.logging import get_logger

log = get_logger(__name__)

_GH_API = os.getenv("GITHUB_API", "https://api.github.com")
_APP_ID = os.getenv("GITHUB_APP_ID", "")
_INSTALL_ID = os.getenv("GITHUB_INSTALLATION_ID", "")

_cached_token: dict[str, str | float] = {"token": "", "exp": 0.0}

def _ensure_private_key() -> str:
    key = os.environ.get("GITHUB_PRIVATE_KEY")
    if key:
        if "BEGIN RSA PRIVATE KEY" in key or "BEGIN PRIVATE KEY" in key:
            return key
        try:
            return base64.b64decode(key).decode("utf-8")
        except Exception:
            return key

    key_path = os.environ.get("GITHUB_PRIVATE_KEY_PATH")
    if key_path:
        path = Path(key_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise RuntimeError(f"GITHUB_PRIVATE_KEY_PATH not found: {path}")
        return path.read_text()

    raise RuntimeError(
        "Neither GITHUB_PRIVATE_KEY nor GITHUB_PRIVATE_KEY_PATH is set"
    )

def build_app_jwt(now: Optional[int] = None) -> str:
    if not _APP_ID:
        raise RuntimeError("GITHUB_APP_ID is not set")
    now = now or int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": _APP_ID}
    token = jwt.encode(payload, _ensure_private_key(), algorithm="RS256")
    return token if isinstance(token, str) else token.decode()

def get_installation_token() -> str:
    global _cached_token
    now = time.time()
    if _cached_token["token"] and float(_cached_token["exp"]) - 60 > now:
        return str(_cached_token["token"])
    if not _INSTALL_ID:
        raise RuntimeError("GITHUB_INSTALLATION_ID is not set")
    app_jwt = build_app_jwt()
    url = f"{_GH_API}/app/installations/{_INSTALL_ID}/access_tokens"
    headers = {"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"}
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    token = data["token"]
    _cached_token = {"token": token, "exp": time.time() + float(data.get("expires_in", 3600))}
    log.info("[github-auth] obtained installation token")
    return token
