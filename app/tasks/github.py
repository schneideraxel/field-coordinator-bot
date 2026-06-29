# app/tasks/github.py
# GitHub tasks
# AS 🐚🫧🪼🪸
# 21.04.2026 (Last update)

from __future__ import annotations

import json
from typing import Any, Dict

from dateutil.parser import parse as parse_date

from app.tasks.base import BaseTask, TaskRegistry
from app.core.context import TaskContext
from app.adapters.github.client import GitHubClient


def _get_client(ctx: TaskContext, repo: str) -> "GitHubClient":
    key = f"__gh_client__{repo}"
    client = ctx.get_shared(key)
    if client is None:
        client = GitHubClient(repo=repo)
        ctx.set_shared(key, client)
    return client


def _parse_updates(val: Any) -> Dict[str, Any]:
    if isinstance(val, dict):
        return val
    if isinstance(val, str) and val.strip():
        return json.loads(val)
    return {}


def extract_field_updates(params: Dict[str, Any]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    for k, v in params.items():
        if not k.startswith("field_"):
            continue
        if k.startswith("field_date_") and isinstance(v, str):
            try:
                updates[k] = parse_date(v).date().isoformat()
                continue
            except Exception:
                pass
        updates[k] = v
    return updates


@TaskRegistry.register("create_issue")
class CreateGitHubIssue(BaseTask):
    def run(self, context: TaskContext):
        repo = self.params.get("repo") or context.payload.get("repo")
        title = (
            self.params.get("title")
            or context.payload.get("title")
            or self.params.get("case")
            or context.payload.get("case")
            or "Automated Issue"
        )
        body = self.params.get("body") or context.payload.get("body") or ""
        labels = context.payload.get("labels")
        client = _get_client(context, repo)
        number = client.create_issue(title=title, body=body, labels=labels)
        context.set_result("issue_number", number)
        context.set_result("issue_node_id", client.get_issue_node_id(number))


@TaskRegistry.register("post_comment")
class PostGitHubComment(BaseTask):
    def run(self, context: TaskContext):
        repo = self.params.get("repo") or context.payload.get("repo")
        client = _get_client(context, repo)
        issue_number = (
            self.params.get("issue_number")
            or context.payload.get("issue_number")
            or context.get_result("created_issue_number")
            or context.get_result("issue_number")
        )
        if not issue_number:
            title = self.params.get("case") or self.params.get("title")
            if title:
                issue_number = client.find_issue_by_title(title)
        comment = self.params.get("comment") or context.payload.get("comment") or ""
        if issue_number and comment:
            client.post_comment(int(issue_number), comment)


@TaskRegistry.register("ensure_project_exists")
class EnsureGitHubProjectExists(BaseTask):
    def run(self, context: TaskContext):
        project = self.params.get("project") or context.payload.get("project")
        repo = self.params.get("repo") or context.payload.get("repo")
        if project:
            client = _get_client(context, repo)
            pid = client.ensure_project(project)
            context.set_result("project_id", pid)


@TaskRegistry.register("ensure_project_item_exists")
class EnsureProjectItemExists(BaseTask):
    def run(self, context: TaskContext):
        project = self.params.get("project") or context.payload.get("project")
        repo = self.params.get("repo") or context.payload.get("repo")
        issue_node_id = (
            self.params.get("issue_node_id")
            or context.get_result("issue_node_id")
        )
        if project and issue_node_id:
            client = _get_client(context, repo)
            item_id = client.ensure_project_item(project, issue_node_id)
            context.set_result("project_item_id", item_id)


@TaskRegistry.register("update_project_field")
class UpdateGitHubProjectField(BaseTask):
    def run(self, context: TaskContext):
        project = self.params.get("project") or context.payload.get("project")
        item_id = self.params.get("item_id") or context.get_result("project_item_id")
        field = self.params.get("field") or self.params.get("field_name")
        value = self.params.get("value") or self.params.get("field_value")
        if project and item_id and field:
            client = _get_client(context, self.params.get("repo") or context.payload.get("repo"))
            client.update_item_field(project, item_id, field, value)


@TaskRegistry.register("update_multiple_github_fields")
class UpdateMultipleGitHubFields(BaseTask):
    def run(self, context: TaskContext):
        project = self.params.get("project") or context.payload.get("project")
        item_id = self.params.get("item_id") or context.get_result("project_item_id")
        updates = extract_field_updates(
            _parse_updates(self.params.get("updates") or context.payload.get("updates"))
        )
        if project and item_id and updates:
            client = _get_client(context, self.params.get("repo") or context.payload.get("repo"))
            client.update_item_fields(project, item_id, updates)


@TaskRegistry.register("sync_issue")
class SyncGitHubIssue(BaseTask):
    def run(self, ctx: TaskContext) -> None:
        repo = self.params.get("repo") or ctx.payload.get("repo")
        title = (
            self.params.get("title")
            or ctx.payload.get("title")
            or self.params.get("case")
            or ctx.payload.get("case")
            or "Automated Issue"
        )
        body = self.params.get("body") or ctx.payload.get("body") or ""
        labels = ctx.payload.get("labels")

        if not repo:
            ctx.log("[sync_issue] ERROR: missing repo")
            return

        opts = [o.lower() for o in self.params.get("options", [])]
        ctx.log(f"[sync_issue] Received options: {opts}")

        client = _get_client(ctx, repo)
        issue_number = client.find_issue_by_title(title)

        if issue_number:
            if "skip" in opts and "update" not in opts and "comment" not in opts:
                ctx.log(f"[sync_issue] Issue already exists (#{issue_number}), skipping (options={opts})")
                ctx.set_result("issue_number", issue_number)
                ctx.set_result("issue_node_id", client.get_issue_node_id(issue_number))
                return

            ctx.log(f"[sync_issue] Issue already exists (#{issue_number}), syncing (options={opts})")
            if body and "comment" in opts:
                client.post_comment(issue_number, body)
                ctx.log(f"[sync_issue] Posted comment to #{issue_number}")
            elif body and "update" in opts:
                client.update_issue_body(issue_number, body)
                ctx.log(f"[sync_issue] Updated issue body for #{issue_number}")
            if labels:
                try:
                    client.update_issue_labels(issue_number, labels)
                    ctx.log(f"[sync_issue] Updated labels for #{issue_number}: {labels}")
                except Exception as e:
                    ctx.log(f"[sync_issue] WARNING: could not update labels for #{issue_number}: {e}")
            ctx.set_result("issue_number", issue_number)
            ctx.set_result("issue_node_id", client.get_issue_node_id(issue_number))
            return

        ctx.log(f"[sync_issue] No existing issue found, creating new one (options={opts})")
        issue_number = client.create_issue(title=title, body=body, labels=labels)
        ctx.set_result("issue_number", issue_number)
        ctx.set_result("issue_node_id", client.get_issue_node_id(issue_number))
        ctx.log(f"[sync_issue] Created new issue #{issue_number}")



@TaskRegistry.register("sync_project")
class SyncGitHubProjectTask(BaseTask):
    def run(self, ctx: TaskContext) -> None:
        repo = self.params.get("repo") or ctx.payload.get("repo")
        project_title = self.params.get("project") or ctx.payload.get("project")
        issue_number = (
            self.params.get("issue_number")
            or ctx.payload.get("issue_number")
            or ctx.get_result("issue_number")
        )
        issue_node_id = (
            self.params.get("issue_node_id")
            or ctx.payload.get("issue_node_id")
            or ctx.get_result("issue_node_id")
        )

        if not repo or not project_title or not issue_node_id:
            ctx.log("[sync_project] ERROR: missing repo, project or issue_node_id")
            return

        opts = [o.lower() for o in self.params.get("options", [])]
        ctx.log(f"[sync_project] Received options: {opts}")

        client = _get_client(ctx, repo)

        project_id = client.ensure_project(project_title)
        ctx.set_result("project_id", project_id)
        ctx.log(f"[sync_project] Project '{project_title}' ready (id={project_id})")

        is_new_item = False
        existing_item = client.find_project_item(project_title, issue_node_id, project_id=project_id)


        if existing_item:
            item_id = existing_item["id"]
            ctx.set_result("project_item_id", item_id)
            ctx.log(f"[sync_project] Issue node {issue_node_id} already exists as item {item_id}")
        else:
            item_id = client.ensure_project_item(project_title, issue_node_id, project_id=project_id)
            ctx.set_result("project_item_id", item_id)
            ctx.log(f"[sync_project] Issue node {issue_node_id} added as item {item_id}")
            is_new_item = True

        if not is_new_item and "skip" in opts and "update" not in opts:
            ctx.log(f"[sync_project] Item already exists, skipping all project mutations (options={opts})")
            return

        combined_inputs = {**ctx.payload, **self.params}
        updates = extract_field_updates(combined_inputs)

        if updates:
            client.update_item_fields(project_id, item_id, updates)
            ctx.log(f"[sync_project] Updated fields for issue #{issue_number}: {list(updates.keys())}")
        else:
            ctx.log("[sync_project] No updates found, skipping update_item_fields")



@TaskRegistry.register("delete_issue")
class DeleteGitHubIssues(BaseTask):
    def run(self, ctx: TaskContext) -> None:
        repo = self.params.get("repo") or ctx.payload.get("repo")
        if not repo:
            ctx.log("[delete_issue] ERROR: missing repo")
            return

        opts_raw = self.params.get("options") or []
        opts_val = (opts_raw[0].strip() if isinstance(opts_raw, list) else str(opts_raw).strip())
        limit = None

        if not opts_val:
            ctx.log("[delete_issue] ERROR: missing options (must be 'all' or a number)")
            return

        if opts_val.lower() == "all":
            limit = None
        elif opts_val.isdigit():
            limit = int(opts_val)
        else:
            ctx.log(f"[delete_issue] ERROR: invalid options='{opts_val}' (must be 'all' or a number)")
            return

        client = _get_client(ctx, repo)
        ctx.log(f"[delete_issue] Starting purge on repo={repo}, limit={'ALL' if limit is None else limit}")

        per_page = 100
        deleted = 0
        page = 1

        while True:
            issues = client.list_issues(page=page, per_page=per_page, state="all")
            if not issues:
                break

            for issue in issues:
                if "pull_request" in issue:
                    continue

                number = issue["number"]
                try:
                    success = client.purge_issue(None, number)
                    if success:
                        ctx.log(f"[delete_issue] Soft-deleted issue #{number}")
                    else:
                        ctx.log(f"[delete_issue] WARNING: issue #{number} could not be soft-deleted")
                except Exception as e:
                    ctx.log(f"[delete_issue] WARNING: exception while deleting issue #{number}: {e}")

                deleted += 1
                if limit is not None and deleted >= limit:
                    ctx.log(f"[delete_issue] Reached limit {limit}, stopping.")
                    ctx.set_result("deleted_count", deleted)
                    return

            page += 1

        ctx.set_result("deleted_count", deleted)
        ctx.log(f"[delete_issue] Completed purge, deleted {deleted} issues")
