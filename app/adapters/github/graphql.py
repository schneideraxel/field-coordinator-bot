# app/adapters/github/graphql.py
# GraphQL V4 helper
# AS 🐚🫧🪼🪸
# 14.08.2025 (Last update)

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from app.core.logging import get_logger
from app.adapters.github.auth import get_installation_token

log = get_logger(__name__)
_GH_GQL = os.getenv("GITHUB_GRAPHQL_URL") or os.getenv("GITHUB_GRAPHQL", "https://api.github.com/graphql")

class GitHubGraphQL:
    def __init__(self, token: Optional[str] = None):
        self._token = token

    def _headers(self) -> Dict[str, str]:
        token = self._token or get_installation_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }

    def run(self, query: str, variables: Dict[str, Any] | None = None) -> Dict[str, Any]:
        with httpx.Client(timeout=30) as c:
            r = c.post(_GH_GQL, headers=self._headers(), json={"query": query, "variables": variables or {}})
            log.info(f"[github-graphql] POST -> {r.status_code}")
            r.raise_for_status()
            data = r.json()
        if "errors" in data and data["errors"]:
            raise RuntimeError(f"GraphQL error(s): {data['errors']}")
        return data["data"]

    def execute(
        self,
        query: str,
        variables: Dict[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> Dict[str, Any]:
        if operation_name:
            log.debug(f"[github-graphql] operation={operation_name}")
        return self.run(query, variables)


GraphQLClient = GitHubGraphQL
