# app/adapters/github/http.py
# httpx wrapper with auth headers
# AS 🐚🫧🪼🪸
# 15.09.2025 (Last update)

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from app.core.logging import get_logger
from app.adapters.github.auth import get_installation_token

log = get_logger(__name__)
_GH_API = os.getenv("GITHUB_API", "https://api.github.com")

class GitHubHTTP:
    def __init__(self, token: Optional[str] = None):
        self._token = token

    def _headers(self) -> Dict[str, str]:
        token = self._token or get_installation_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get(self, path: str, params: Dict[str, Any] | None = None) -> httpx.Response:
        url = path if path.startswith("http") else f"{_GH_API}{path}"
        with httpx.Client(timeout=30) as c:
            r = c.get(url, headers=self._headers(), params=params)
            log.info(f"[github-http] GET {url} -> {r.status_code}")
            r.raise_for_status()
            return r

    def post(self, path: str, json: Dict[str, Any] | None = None) -> httpx.Response:
        url = path if path.startswith("http") else f"{_GH_API}{path}"
        with httpx.Client(timeout=30) as c:
            r = c.post(url, headers=self._headers(), json=json)
            log.info(f"[github-http] POST {url} -> {r.status_code}")
            r.raise_for_status()
            return r

    def patch(self, path: str, json: Dict[str, Any] | None = None) -> httpx.Response:
        url = path if path.startswith("http") else f"{_GH_API}{path}"
        with httpx.Client(timeout=30) as c:
            r = c.patch(url, headers=self._headers(), json=json)
            log.info(f"[github-http] PATCH {url} -> {r.status_code}")
            r.raise_for_status()
            return r

    def put(self, path: str, json: Dict[str, Any] | None = None) -> httpx.Response:
        url = path if path.startswith("http") else f"{_GH_API}{path}"
        with httpx.Client(timeout=30) as c:
            r = c.put(url, headers=self._headers(), json=json)
            log.info(f"[github-http] PUT {url} -> {r.status_code}")
            r.raise_for_status()
            return r

    def delete(self, path: str, json: Dict[str, Any] | None = None) -> httpx.Response:
        url = path if path.startswith("http") else f"{_GH_API}{path}"
        with httpx.Client(timeout=30) as c:
            r = c.delete(url, headers=self._headers(), json=json)
            log.info(f"[github-http] DELETE {url} -> {r.status_code}")
            r.raise_for_