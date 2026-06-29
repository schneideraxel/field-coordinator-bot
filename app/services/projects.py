# app/services/projects.py

# app/services/projects.py
# ProjectsService: resolve/create project, ensure items (issue/draft), idempotent
# AS 🐚🫧🪼🪸
# 12.08.2025 (Last update)

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from app.adapters.github.graphql import GraphQLClient
from app.core.logging import get_logger

logger = get_logger(__name__)


def _marker(project_id: str, title: str) -> str:
    norm = " ".join(title.split()).lower().encode("utf-8")
    return f"<!-- gh-automation:key={project_id}:{hashlib.sha256(norm).hexdigest()[:16]} -->"


class ProjectsService:
    def __init__(self, gql: GraphQLClient):
        self.gql = gql

    # ---------- Project resolution ----------
    def get_project_by_title(self, owner_login: str, title: str) -> Optional[Dict[str, Any]]:
        # Try organization first, then user
        data_org = self.gql.execute(
            """
            query($owner:String!, $title:String!){
              organization(login:$owner){
                projectsV2(first:20, query:$title){
                  nodes { id title number }
                }
              }
            }
            """,
            {"owner": owner_login, "title": title},
            operation_name="OrgProjectsByTitle",
        )
        org = data_org.get("organization")
        if org:
            for p in org.get("projectsV2", {}).get("nodes", []):
                if p["title"].strip().lower() == title.strip().lower():
                    return p
        data_user = self.gql.execute(
            """
            query($owner:String!, $title:String!){
              user(login:$owner){
                projectsV2(first:20, query:$title){
                  nodes { id title number }
                }
              }
            }
            """,
            {"owner": owner_login, "title": title},
            operation_name="UserProjectsByTitle",
        )
        usr = data_user.get("user")
        if usr:
            for p in usr.get("projectsV2", {}).get("nodes", []):
                if p["title"].strip().lower() == title.strip().lower():
                    return p
        return None

    def create_project(self, owner_id: str, title: str) -> Dict[str, Any]:
        data = self.gql.execute(
            """
            mutation($owner:ID!, $title:String!){
              createProjectV2(input:{ownerId:$owner, title:$title}){
                projectV2 { id title number }
              }
            }
            """,
            {"owner": owner_id, "title": title},
            operation_name="CreateProjectV2",
        )
        return data["createProjectV2"]["projectV2"]

    def get_or_create_project_by_title(self, owner_login: str, owner_id: str, title: str) -> Dict[str, Any]:
        found = self.get_project_by_title(owner_login, title)
        if found:
            return found
        created = self.create_project(owner_id, title)
        # verify-after-create
        return self.get_project_by_title(owner_login, title) or created

    # ---------- Items (issue-based) ----------
    def get_item_id_by_issue_node(self, project_id: str, issue_node_id: str) -> Optional[str]:
        data = self.gql.execute(
            """
            query($pid:ID!, $issue:ID!){
              node(id:$pid){
                ... on ProjectV2 {
                  items(first:100, filter:{contentId:$issue}) {
                    nodes { id content { __typename } }
                  }
                }
              }
            }
            """,
            {"pid": project_id, "issue": issue_node_id},
            operation_name="ProjectItemsByIssue",
        )
        items = data.get("node", {}).get("items", {}).get("nodes", [])
        return items[0]["id"] if items else None

    def add_issue_item(self, project_id: str, issue_node_id: str) -> str:
        data = self.gql.execute(
            """
            mutation($pid:ID!, $issue:ID!){
              addProjectV2ItemById(input:{projectId:$pid, contentId:$issue}){
                item { id }
              }
            }
            """,
            {"pid": project_id, "issue": issue_node_id},
            operation_name="AddIssueItemToProject",
        )
        return data["addProjectV2ItemById"]["item"]["id"]

    def get_or_create_issue_item(self, project_id: str, issue_node_id: str) -> str:
        existing = self.get_item_id_by_issue_node(project_id, issue_node_id)
        if existing:
            return existing
        self.add_issue_item(project_id, issue_node_id)
        return self.get_item_id_by_issue_node(project_id, issue_node_id)  # verify

    # ---------- Draft items ----------
    def create_draft_item(self, project_id: str, title: str, body: str | None = None) -> str:
        marker = _marker(project_id, title)
        body2 = (body or "") + "\n" + marker
        data = self.gql.execute(
            """
            mutation($pid:ID!, $title:String!, $body:String){
              createProjectV2DraftIssue(input:{projectId:$pid, title:$title, body:$body}){
                projectItem { id }
              }
            }
            """,
            {"pid": project_id, "title": title, "body": body2},
            operation_name="CreateDraftItem",
        )
        return data["createProjectV2DraftIssue"]["projectItem"]["id"]

    def ensure_unique_draft_item(self, project_id: str, title: str, body: str | None = None) -> str:
        # Without an API to search draft bodies, we create and rely on higher-level
        # idempotency markers or a dedicated Notes field if available.
        return self.create_draft_item(project_id, title, body)

