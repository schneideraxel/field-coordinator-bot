# app/services/issues.py

# app/services/issues.py
# IssuesService: exact-title search, idempotent create-or-get, comments
# AS 🐚🫧🪼🪸
# 12.08.2025 (Last update)

from __future__ import annotations

from typing import Any, Dict, Optional

from app.adapters.github.graphql import GraphQLClient
from app.adapters.github.http import HttpClient
from app.core.logging import get_logger

logger = get_logger(__name__)


class IssuesService:
    def __init__(self, http: HttpClient, gql: GraphQLClient, owner: str, repo: str):
        self.http = http
        self.gql = gql
        self.owner = owner
        self.repo = repo

    @property
    def repo_slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    def find_issue_by_exact_title(self, title: str) -> Optional[Dict[str, Any]]:
        q = f'repo:{self.repo_slug} is:issue in:title "{title}"'
        data = self.gql.execute(
            """
            query($q:String!){
              search(type:ISSUE, query:$q, first:10){
                nodes { ... on Issue { number id title url } }
              }
            }
            """,
            {"q": q},
            operation_name="SearchIssueByTitle",
        )
        wanted = title.strip().lower()
        for n in data.get("search", {}).get("nodes", []):
            if n["title"].strip().lower() == wanted:
                return n
        return None

    def create_issue(self, title: str, body: Optional[str] = None) -> Dict[str, Any]:
        path = f"repos/{self.owner}/{self.repo}/issues"
        r = self.http.rest("POST", path, json={"title": title, "body": body or ""})
        return r.json()

    def get_or_create_issue(self, title: str, body: Optional[str] = None) -> Dict[str, Any]:
        found = self.find_issue_by_exact_title(title)
        if found:
            return found
        created = self.create_issue(title, body=body)
        # verify-after-create (handles retries/concurrency)
        return self.find_issue_by_exact_title(title) or created

    def post_comment(self, issue_number: int, body: str) -> Dict[str, Any]:
        path = f"repos/{self.owner}/{self.repo}/issues/{issue_number}/comments"
        r = self.http.rest("POST", path, json={"body": body})
        return r.json()

