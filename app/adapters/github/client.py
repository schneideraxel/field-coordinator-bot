# app/adapters/github/client.py
# GitHubClient (REST/GraphQL)
# AS 🐚🫧🪼🪸
# 23.01.2025 (Last update)

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

from dateutil.parser import parse as parse_date

from app.core.logging import get_logger
from app.adapters.github.http import GitHubHTTP
from app.adapters.github.graphql import GitHubGraphQL

log = get_logger(__name__)


def _split_repo(repo: str) -> Tuple[str, str]:
    if not repo or "/" not in repo:
        raise ValueError("repo must be 'owner/name'")
    owner, name = repo.split("/", 1)
    return owner, name


def _strip_field_prefix(name: str) -> str:
    for prefix in ("field_text_", "field_number_", "field_date_", "field_single_"):
        if name.lower().startswith(prefix):
            return name[len(prefix):]
    return name


@dataclass
class _ProjectField:
    id: str
    name: str
    data_type: str
    options: Dict[str, str]
    options_full: List[Dict[str, Any]]
    iterations: Dict[str, str]


class GitHubClient:
    """
    Adapter facade: Issues (REST) + Projects v2 (GraphQL).
    """

    def __init__(self, repo: Optional[str] = None, token: Optional[str] = None):
        self.repo = repo
        self.http = GitHubHTTP(token=token)
        self.gql = GitHubGraphQL(token=token)

        self._project_cache: dict[Tuple[str, str], str] = {}
        self._owner_cache: dict[str, Tuple[str, str]] = {}
        self._fields_cache: dict[str, dict[str, _ProjectField]] = {}
        self._item_values_cache: dict[str, dict[str, Any]] = {}
        self._project_items_cache: dict[str, dict[str, dict]] = {}
        self._repo_labels_cache: dict[str, dict[str, Any]] | None = None


    def create_issue(self, title: str, body: str = "", labels: Optional[list[str]] = None) -> int:
        if not self.repo:
            raise ValueError("repo is required for create_issue")
        owner, name = _split_repo(self.repo)
        payload: Dict[str, Any] = {"title": title, "body": body}

        if labels:
            if isinstance(labels, str):
                labels = [l.strip() for l in labels.split(",") if l.strip()]
            elif isinstance(labels, (int, float)):
                labels = [str(labels)]
            elif isinstance(labels, list):
                labels = [str(l).strip() for l in labels if str(l).strip()]
            else:
                labels = [str(labels).strip()]

            if labels:
                log.info(f"[github] ensuring labels exist: {labels}")
                self._ensure_labels_exist(labels)
                payload["labels"] = labels
                log.info(f"[github] creating issue with labels={labels}")

        r = self.http.post(f"/repos/{owner}/{name}/issues", json=payload)
        data = r.json()
        num = int(data["number"])
        applied_labels = [lbl.get("name") for lbl in data.get("labels", [])]
        log.info(f"[github] created issue #{num} in {self.repo} with labels={applied_labels}")

        return num

    def post_comment(self, issue_number: int, body: str) -> None:
        if not self.repo:
            raise ValueError("repo is required for post_comment")
        owner, name = _split_repo(self.repo)
        self.http.post(f"/repos/{owner}/{name}/issues/{issue_number}/comments", json={"body": body})
        log.info(f"[github] commented on issue #{issue_number}")

    def update_issue_body(self, issue_number: int, body: str) -> None:
        if not self.repo:
            raise ValueError("repo is required for update_issue_body")
        owner, name = _split_repo(self.repo)
        self.http.patch(f"/repos/{owner}/{name}/issues/{issue_number}", json={"body": body})
        log.info(f"[github] updated issue body for #{issue_number}")

    def find_issue_by_title(self, title: str) -> Optional[int]:
        if not self.repo:
            raise ValueError("repo is required for find_issue_by_title")
        owner, name = _split_repo(self.repo)
        q = f'repo:{owner}/{name} type:issue in:title "{title}"'
        r = self.http.get("/search/issues", params={"q": q, "per_page": 1})
        items = r.json().get("items", [])
        if items:
            return int(items[0]["number"])
        return None

    def get_issue_node_id(self, number: int) -> str:
        if not self.repo:
            raise ValueError("repo is required for get_issue_node_id")
        owner, name = _split_repo(self.repo)
        query = """
        query($owner:String!, $name:String!, $number:Int!) {
          repository(owner:$owner, name:$name) { issue(number:$number) { id } }
        }
        """
        data = self.gql.run(query, {"owner": owner, "name": name, "number": int(number)})
        return data["repository"]["issue"]["id"]

    def _get_owner(self, login: str) -> Tuple[str, str]:
        if login in self._owner_cache:
            return self._owner_cache[login]
        query = """
        query($login:String!) {
          organization(login:$login) { id }
          user(login:$login) { id }
        }
        """
        data = self.gql.run(query, {"login": login})
        if data.get("organization") and data["organization"]:
            node_id = data["organization"]["id"]
            self._owner_cache[login] = ("ORG", node_id)
            return "ORG", node_id
        if data.get("user") and data["user"]:
            node_id = data["user"]["id"]
            self._owner_cache[login] = ("USER", node_id)
            return "USER", node_id
        raise RuntimeError(f"Owner not found: {login}")

    def _list_projects(self, login: str, first: int = 50) -> list[dict]:
        query = """
        query($login:String!, $first:Int!) {
          organization(login:$login) { projectsV2(first:$first) { nodes { id title } } }
          user(login:$login) { projectsV2(first:$first) { nodes { id title } } }
        }
        """
        data = self.gql.run(query, {"login": login, "first": first})
        nodes: list[dict] = []
        if data.get("organization") and data["organization"]:
            nodes.extend(data["organization"]["projectsV2"]["nodes"])
        if data.get("user") and data["user"]:
            nodes.extend(data["user"]["projectsV2"]["nodes"])
        return nodes

    def ensure_project(self, project_title: str) -> str:
        """
        Look up a ProjectV2 by title under the org owner.
        If not found, create it robustly (handles pagination + normalization).
        Returns the project ID.
        """
        org, _repo = self.repo.split("/", 1)

        def _norm(s: str) -> str:
            return " ".join((s or "").split()).casefold()

        cache_key = (org, _norm(project_title))
        if cache_key in self._project_cache:
            return self._project_cache[cache_key]

        query = """
        query($org: String!, $first: Int!, $after: String) {
          organization(login: $org) {
            id
            projectsV2(first: $first, after: $after) {
              nodes { id title number }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
        """

        all_projects = []
        after = None
        while True:
            log.debug(f"[github] ensure_project: querying org={org}, after={after}")
            data = self.gql.run(query, {"org": org, "first": 50, "after": after})
            org_node = (data or {}).get("organization")
            if not org_node:
                raise RuntimeError(
                    f"Organization '{org}' not accessible. "
                    "Check that your GitHub App has 'Projects' read/write permissions "
                    "and that the org has granted access."
                )
            nodes = org_node["projectsV2"]["nodes"]
            page_info = org_node["projectsV2"]["pageInfo"]
            log.debug(f"[github] ensure_project: received {len(nodes)} nodes, page_info={page_info}")
            all_projects.extend(nodes)
            if not page_info.get("hasNextPage"):
                break
            after = page_info["endCursor"]

        log.debug(f"[github] ensure_project: final projects={[p['title'] for p in all_projects]}")

        for p in all_projects:
            if _norm(p["title"]) == _norm(project_title):
                log.info(f"[github] found existing project '{project_title}' (id={p['id']}) in org={org}")
                self._project_cache[cache_key] = p["id"]
                return p["id"]

        log.info(f"[github] project '{project_title}' not found in org={org}, creating it...")
        log.debug(f"[github] ensure_project: creating project with orgId={org_node['id']}")

        mutation = """
        mutation($orgId: ID!, $title: String!) {
          createProjectV2(input: {ownerId: $orgId, title: $title}) {
            projectV2 { id title }
          }
        }
        """
        resp = self.gql.run(mutation, {"orgId": org_node["id"], "title": project_title})
        log.debug(f"[github] ensure_project: mutation response={resp}")
        project = (resp.get("createProjectV2") or {}).get("projectV2")
        if not project:
            raise RuntimeError(f"Failed to create project '{project_title}' in org={org}")

        log.info(f"[github] created project '{project['title']}' (id={project['id']}) in org={org}")
        self._project_cache[(org, _norm(project["title"]))] = project["id"]
        return project["id"]


    def _get_field_by_name(self, project_id: str, name: str) -> Optional[_ProjectField]:
        """Lookup a field by name (case-insensitive)."""
        fields = self._get_project_fields(project_id)
        return fields.get((name or "").lower())

    def get_or_create_issue_item(self, project_id: str, issue_node_id: str) -> str:
        """
        Add an issue (by node ID) to a project, or return existing item if it already exists.
        """
        mutation = """
        mutation($projectId:ID!, $contentId:ID!) {
          addProjectV2ItemById(input:{projectId:$projectId, contentId:$contentId}) {
            item { id }
          }
        }
        """
        data = self.gql.run(mutation, {"projectId": project_id, "contentId": issue_node_id})
        item = data["addProjectV2ItemById"]["item"]
        self._project_items_cache.setdefault(project_id, {})[issue_node_id] = item
        return item["id"]

    def ensure_project_item(self, project_title: str, issue_node_id: str, project_id: str | None = None) -> str:
        project_id = project_id or self.ensure_project(project_title)
        item_id = self.get_or_create_issue_item(project_id, issue_node_id)

        try:
            self._set_item_status(project_id, item_id, "Todo")
        except Exception as e:
            log.warning(f"[github] failed to set default Status on new item: {e}")

        return item_id

    def _get_project_fields(self, project_id: str) -> dict[str, _ProjectField]:
        if project_id in self._fields_cache:
            return self._fields_cache[project_id]

        query = """
        query($projectId:ID!) {
          node(id:$projectId) {
            ... on ProjectV2 {
              fields(first:100) {
                nodes {
                  __typename

                  ... on ProjectV2Field {
                    id
                    name
                    dataType
                  }

                  ... on ProjectV2SingleSelectField {
                    id
                    name
                    dataType
                    options { id name color description }
                  }

                  ... on ProjectV2IterationField {
                    id
                    name
                    dataType
                    configuration { iterations { id title startDate duration } }
                  }
                }
              }
            }
          }
        }
        """

        log.debug(f"[github] _get_project_fields: querying project_id={project_id}")
        data = self.gql.run(query, {"projectId": project_id})
        log.debug(f"[github] _get_project_fields: raw data keys={list((data or {}).keys())}")

        fields: dict[str, _ProjectField] = {}
        nodes = (data or {}).get("node", {}).get("fields", {}).get("nodes", []) or []
        log.debug(f"[github] _get_project_fields: nodes count={len(nodes)}")

        for node in nodes:
            name = node.get("name")
            if not name:
                continue

            t = node.get("__typename")
            dt = node.get("dataType")
            log.debug(f"[github] _get_project_fields: parsing field={name}, typename={t}, dataType={dt}")
            if not dt:
                log.warning(f"[github] field '{name}' has no dataType (typename={t})")
                dt = "UNKNOWN"

            options_map: Dict[str, str] = {}
            options_full: List[Dict[str, Any]] = []
            if t == "ProjectV2SingleSelectField":
                for opt in node.get("options") or []:
                    options_map[(opt.get("name") or "").lower()] = opt.get("id")
                    options_full.append({
                        "id": opt.get("id"),
                        "name": opt.get("name"),
                        "color": opt.get("color"),
                        "description": opt.get("description"),
                    })

            iterations: Dict[str, str] = {}
            if t == "ProjectV2IterationField":
                cfg = node.get("configuration") or {}
                for it in (cfg.get("iterations") or []):
                    iterations[(it.get("title") or "").lower()] = it.get("id")

            fields[name.lower()] = _ProjectField(
                id=node.get("id"),
                name=name,
                data_type=dt,
                options=options_map,
                options_full=options_full,
                iterations=iterations,
            )

        self._fields_cache[project_id] = fields

        log.info(f"[github] fetched {len(fields)} fields for project {project_id}:")
        for f in fields.values():
            if f.data_type == "SINGLE_SELECT":
                log.info(
                    f"  - {f.name} (id={f.id}, type={f.data_type}, "
                    f"options={[o['name'] for o in f.options_full]})"
                )
            elif f.data_type == "ITERATION":
                log.info(
                    f"  - {f.name} (id={f.id}, type={f.data_type}, "
                    f"iterations={list(f.iterations.keys())})"
                )
            else:
                log.info(f"  - {f.name} (id={f.id}, type={f.data_type})")

        return fields

    def _infer_field_type(self, field_name: str, raw: Any) -> str:
        prefix_map = {
            "field_text_": "TEXT",
            "field_number_": "NUMBER",
            "field_date_": "DATE",
            "field_single_": "SINGLE_SELECT",
        }
        fname_lower = field_name.lower()
        for prefix, ftype in prefix_map.items():
            if fname_lower.startswith(prefix):
                return ftype
        try:
            _ = float(raw)
            return "NUMBER"
        except Exception:
            pass
        try:
            _ = parse_date(str(raw)).date()
            return "DATE"
        except Exception:
            pass
        return "TEXT"


    def _create_field(self, project_id: str, name: str, data_type: str,
                      initial_option: Optional[str] = None) -> _ProjectField:
        log.debug(f"[github] _create_field: creating field name={name}, data_type={data_type}, project_id={project_id}, initial_option={initial_option}")

        options_input = None
        if data_type == "SINGLE_SELECT":
            seed_value = str(initial_option).strip() if initial_option and str(
                initial_option).strip() else "unspecified"
            options_input = [{
                "name": seed_value,
                "color": "GRAY",
                "description": ""
            }]

        mutation = """
        mutation($projectId:ID!, $name:String!, $dataType:ProjectV2CustomFieldType!, $opts:[ProjectV2SingleSelectFieldOptionInput!]) {
          createProjectV2Field(
            input:{projectId:$projectId, name:$name, dataType:$dataType, singleSelectOptions:$opts}
          ) {
            projectV2Field {
              __typename
              ... on ProjectV2Field { id name dataType }
              ... on ProjectV2SingleSelectField { options { id name color description } }
              ... on ProjectV2IterationField { configuration { iterations { id title startDate duration } } }
            }
          }
        }
        """

        try:
            resp = self.gql.run(mutation, {
                "projectId": project_id,
                "name": name,
                "dataType": data_type,
                "opts": options_input,
            })
            log.debug(f"[github] _create_field: mutation response={resp}")
        except Exception as e:
            msg = str(e)
            log.debug(f"[github] _create_field: exception={msg}")
            if "Name has already been taken" in msg or "already been taken" in msg:
                self._fields_cache.pop(project_id, None)
                existing = self._get_field_by_name(project_id, name)
                if existing:
                    log.info(f"[github] field '{name}' already exists (type={existing.data_type}); using existing.")
                    return existing
            raise

        fld_data = (resp.get("createProjectV2Field") or {}).get("projectV2Field")
        log.debug(f"[github] _create_field: resolved fld_data={fld_data}")
        if not fld_data:
            self._fields_cache.pop(project_id, None)
            existing = self._get_field_by_name(project_id, name)
            if existing:
                log.info(f"[github] field '{name}' already exists (type={existing.data_type}); using existing.")
                return existing
            raise RuntimeError(f"Field '{name}' was not created on project {project_id}")

        self._fields_cache.pop(project_id, None)
        fields = self._get_project_fields(project_id)
        fld = fields.get(name.lower())

        log.info(f"[github] created field '{name}' (type={fld.data_type}) on project={project_id}")
        return fld

    def _update_single_select_options(self, project_id: str, field: _ProjectField, new_option_name: str) -> None:
        log.debug(
            f"[github] _update_single_select_options: field={field.name}, new_option_name={new_option_name}, project_id={project_id}"
        )

        if field.name.lower() == "status":
            log.info("[github] refusing to modify options of built-in 'Status' field; skipping.")
            return

        self._fields_cache.pop(project_id, None)
        fields = self._get_project_fields(project_id)
        field = fields.get(field.name.lower()) or field

        existing = field.options_full or []
        seen_lower = {(opt.get("name") or "").lower() for opt in existing}
        if (new_option_name or "").lower() in seen_lower:
            log.info(f"[github] option '{new_option_name}' already exists on field '{field.name}'")
            return

        new_options_payload: List[Dict[str, Any]] = [
            {
                "name": opt.get("name"),
                "color": opt.get("color"),
                "description": opt.get("description") or "",
            }
            for opt in existing
        ]

        new_options_payload.append({
            "name": str(new_option_name),
            "color": "GRAY",
            "description": ""
        })

        log.debug(f"[github] _update_single_select_options: mutation payload={new_options_payload}")

        mutation = """
        mutation($fieldId:ID!, $options:[ProjectV2SingleSelectFieldOptionInput!]) {
          updateProjectV2Field(
            input:{fieldId:$fieldId, singleSelectOptions:$options}
          ) {
            projectV2Field {
              ... on ProjectV2SingleSelectField {
                id
                name
                options { id name color }
              }
            }
          }
        }
        """

        self.gql.run(mutation, {"fieldId": field.id, "options": new_options_payload})

        self._fields_cache.pop(project_id, None)
        fields = self._get_project_fields(project_id)
        updated = fields.get(field.name.lower())

        if updated:
            log.info(
                f"[github] added single-select option '{new_option_name}' "
                f"to field '{field.name}' on project={project_id}"
            )
        else:
            log.warning(
                f"[github] updated field '{field.name}' but failed to reload it "
                f"after adding option '{new_option_name}'"
            )


    def _get_item_field_values(self, item_id: str, *, refresh: bool = False) -> dict[str, Any]:
        """
        Fetch current field values for a ProjectV2 item.
        Returns a mapping: field_name_lower -> value
        Used to diff before applying updates.
        """
        if not refresh and item_id in self._item_values_cache:
            return self._item_values_cache[item_id]

        query = """
        query($itemId: ID!) {
        node(id: $itemId) {
            ... on ProjectV2Item {
            fieldValues(first: 100) {
                nodes {

                ... on ProjectV2ItemFieldTextValue {
                    field {
                    ... on ProjectV2Field { name }
                    ... on ProjectV2SingleSelectField { name }
                    ... on ProjectV2IterationField { name }
                    }
                    text
                }

                ... on ProjectV2ItemFieldNumberValue {
                    field {
                    ... on ProjectV2Field { name }
                    ... on ProjectV2SingleSelectField { name }
                    ... on ProjectV2IterationField { name }
                    }
                    number
                }

                ... on ProjectV2ItemFieldDateValue {
                    field {
                    ... on ProjectV2Field { name }
                    ... on ProjectV2SingleSelectField { name }
                    ... on ProjectV2IterationField { name }
                    }
                    date
                }

                ... on ProjectV2ItemFieldSingleSelectValue {
                    field {
                    ... on ProjectV2Field { name }
                    ... on ProjectV2SingleSelectField { name }
                    ... on ProjectV2IterationField { name }
                    }
                    name
                }

                ... on ProjectV2ItemFieldIterationValue {
                    field {
                    ... on ProjectV2Field { name }
                    ... on ProjectV2SingleSelectField { name }
                    ... on ProjectV2IterationField { name }
                    }
                    title
                }

                }
            }
            }
        }
        }
        """

        data = self.gql.run(query, {"itemId": item_id})

        nodes = (data or {}).get("node", {}).get("fieldValues", {}).get("nodes", []) or []
        out: dict[str, Any] = {}

        for node in nodes:
            field = ((node.get("field") or {}).get("name") or "").strip().lower()
            if not field:
                continue

            if "text" in node:
                out[field] = node.get("text") or ""
            elif "number" in node:
                out[field] = node.get("number")
            elif "date" in node:
                out[field] = node.get("date")
            elif "title" in node:
                out[field] = node.get("title")
            elif "name" in node:
                out[field] = node.get("name")

        self._item_values_cache[item_id] = out
        log.debug(f"[github] cached field values for item {item_id}: {out}")

        return out



    def update_item_field(self, project_id: str, item_id: str, field_name: str, value: Any) -> None:
        """
        Update a single field on a project item.
        """
        self.update_item_fields(project_id, item_id, {field_name: value})

    def update_item_fields(self, project_id: str, item_id: str, updates: Dict[str, Any]) -> None:
        """
        Update multiple fields on a project item, only mutating fields whose values differ.
        """
        if not updates:
            return

        log.debug(f"[github] update_item_fields: starting updates={updates}, project_id={project_id}, item_id={item_id}")

        fields = self._get_project_fields(project_id)
        existing = self._get_item_field_values(item_id)

        pending_updates: list[tuple[str, _ProjectField, Dict[str, Any], Any]] = []

        for orig_name, raw in updates.items():
            key_name = _strip_field_prefix(orig_name)
            key = key_name.lower()
            fld = fields.get(key)

            log.debug(f"[github] checking field orig_name={orig_name}, key_name={key_name}, raw={raw!r}")

            if not fld:
                inferred = self._infer_field_type(orig_name, raw) or "TEXT"
                try:
                    fld = self._create_field(
                        project_id,
                        key_name,
                        inferred,
                        initial_option=(str(raw) if inferred == "SINGLE_SELECT" else None),
                    )
                    fields = self._fields_cache.get(project_id) or self._get_project_fields(project_id)
                    fld = fields.get(key)
                except Exception as e:
                    log.info(f"[github] failed to auto-create field '{orig_name}': {e}")
                    self._fields_cache.pop(project_id, None)
                    fld = self._get_field_by_name(project_id, key_name)


            if not fld:
                log.info(f"[github] field not found on project: {orig_name} (skipping)")
                continue

            dt = fld.data_type
            log.debug(f"[github] preparing update: field={orig_name}, type={dt}, value={raw!r}, item={item_id}")

            val: Optional[Dict[str, Any]] = None

            if dt == "TEXT":
                if isinstance(raw, (list, tuple)):
                    val = {"text": ", ".join(str(r).strip() for r in raw if str(r).strip())}
                else:
                    val = {"text": "" if raw is None else str(raw)}

            elif dt == "NUMBER":
                try:
                    val = {"number": float(raw)}
                except Exception:
                    log.info(f"[github] non-numeric value for NUMBER field '{orig_name}': {raw!r} (skipping)")
                    continue

            elif dt == "DATE":
                try:
                    val = {"date": parse_date(str(raw)).date().isoformat()}
                except Exception:
                    log.info(f"[github] unparsable DATE for field '{orig_name}': {raw!r} (skipping)")
                    continue

            elif dt == "SINGLE_SELECT":
                if raw is None or str(raw).strip() == "":
                    log.info(f"[github] empty SINGLE_SELECT value for '{orig_name}' (skipping)")
                    continue

                opt_id = fld.options.get(str(raw).lower())
                if not opt_id and fld.name.lower() != "status":
                    try:
                        self._update_single_select_options(project_id, fld, str(raw))
                        fields = self._get_project_fields(project_id)
                        fld = fields.get(key) or fld
                        opt_id = fld.options.get(str(raw).lower())
                    except Exception as e:
                        log.info(f"[github] failed to add option '{raw}' to field '{orig_name}': {e}")

                if not opt_id:
                    log.info(f"[github] option '{raw}' not found for field '{orig_name}' (skipping)")
                    continue

                val = {"singleSelectOptionId": opt_id}

            elif dt == "ITERATION":
                if raw is None or str(raw).strip() == "":
                    log.info(f"[github] empty ITERATION value for '{orig_name}' (skipping)")
                    continue

                it_id = fld.iterations.get(str(raw).lower())
                if not it_id:
                    log.info(f"[github] iteration '{raw}' not found for field '{orig_name}' (skipping)")
                    continue

                val = {"iterationId": it_id}

            else:
                log.info(f"[github] unsupported field type {dt} for '{orig_name}' (skipping)")
                continue

            new_cmp = None
            old_cmp = None

            if dt == "TEXT":
                new_cmp = (val.get("text") or "").strip()
                old_cmp = str(existing.get(key) or "").strip()

            elif dt == "NUMBER":
                new_cmp = val.get("number")
                try:
                    old_cmp = float(existing.get(key)) if existing.get(key) is not None else None
                except Exception:
                    old_cmp = None

            elif dt == "DATE":
                new_cmp = val.get("date")
                old_cmp = existing.get(key) or None

            elif dt == "SINGLE_SELECT":
                new_cmp = str(raw).strip().lower() if raw is not None else None
                old_cmp = (existing.get(key) or "").strip().lower()
                if isinstance(old_cmp, str):
                    old_cmp = old_cmp.strip().lower()

            elif dt == "ITERATION":
                new_cmp = str(raw).strip().lower() if raw is not None else None
                old_cmp = (existing.get(key) or "").strip().lower()
                if isinstance(old_cmp, str):
                    old_cmp = old_cmp.strip().lower()

            if new_cmp == old_cmp:
                log.debug(f"[github] no change for field '{key_name}' (skipping)")
                continue

            pending_updates.append((key, fld, val, new_cmp))

        if not pending_updates:
            return

        variables: Dict[str, Any] = {"projectId": project_id, "itemId": item_id}
        var_defs = ["$projectId:ID!", "$itemId:ID!"]
        mutation_lines: list[str] = []

        for i, (_key, fld, val, _new_cmp) in enumerate(pending_updates, start=1):
            field_var = f"fieldId{i}"
            value_var = f"value{i}"
            var_defs.extend([f"${field_var}:ID!", f"${value_var}:ProjectV2FieldValue!"])
            variables[field_var] = fld.id
            variables[value_var] = val
            mutation_lines.append(
                f"""
                u{i}: updateProjectV2ItemFieldValue(input:{{
                  projectId:$projectId,
                  itemId:$itemId,
                  fieldId:${field_var},
                  value:${value_var}
                }}) {{ projectV2Item {{ id }} }}
                """
            )

        mutation = "mutation UpdateProjectItemFields(" + ", ".join(var_defs) + ") {\n"
        mutation += "\n".join(mutation_lines)
        mutation += "\n}"

        log.debug(f"[github] sending {len(pending_updates)} batched field update(s) for item={item_id}")
        self.gql.run(mutation, variables)

        for key, fld, _val, new_cmp in pending_updates:
            log.info(f"[github] updated field '{fld.name}' on item={item_id}")
            existing[key] = new_cmp

        self._item_values_cache[item_id] = existing




    def _get_repo_labels(self) -> list[dict]:
        if not self.repo:
            raise ValueError("repo is required for _get_repo_labels")
        if self._repo_labels_cache is not None:
            return list(self._repo_labels_cache.values())
        owner, name = _split_repo(self.repo)
        labels: list[dict] = []
        page = 1
        while True:
            r = self.http.get(f"/repos/{owner}/{name}/labels", params={"per_page": 100, "page": page})
            data = r.json() or []
            if not data:
                break
            labels.extend(data)
            if len(data) < 100:
                break
            page += 1
        self._repo_labels_cache = {lbl["name"].lower(): lbl for lbl in labels}
        return labels

    def _ensure_labels_exist(self, label_names: list[str]) -> None:
        if not self.repo:
            raise ValueError("repo is required for _ensure_labels_exist")
        owner, name = _split_repo(self.repo)

        palette = ["B60205", "D93F0B", "FBCA04", "0E8A16", "006B75", "1D76DB", "0052CC", "5319E7", "E99695", "F9D0C4",
                   "FEF2C0", "C2E0C6", "BFDADC", "C5DEF5", "BFD4F2", "D4C5F9"]

        existing = self._repo_labels_cache
        if existing is None:
            existing = {lbl["name"].lower(): lbl for lbl in self._get_repo_labels()}
        for l in label_names:
            lname = l.strip()
            if not lname:
                continue
            if lname.lower() in existing:
                log.debug(
                    f"[github] label '{lname}' already exists "
                    f"(color={existing[lname.lower()]['color']})"
                )
                continue

            idx = abs(hash(lname)) % len(palette)
            color = palette[idx]

            log.info(f"[github] creating missing label '{lname}' with color {color}")
            self.http.post(
                f"/repos/{owner}/{name}/labels",
                json={"name": lname, "color": color},
            )
            existing[lname.lower()] = {"name": lname, "color": color}
            self._repo_labels_cache = existing
            log.info(f"[github] label '{lname}' created successfully")


    def _set_item_status(self, project_id: str, item_id: str, status_value: str = "Todo") -> None:
        fields = self._get_project_fields(project_id)
        status_field = fields.get("status")
        if not status_field:
            log.warning("[github] built-in Status field not found in project; skipping status set")
            return

        opt_id = status_field.options.get(status_value.lower())
        if not opt_id:
            log.warning(f"[github] status option '{status_value}' not found in project; skipping")
            return

        mutation = """
        mutation($projectId:ID!, $itemId:ID!, $fieldId:ID!, $optId:String!) {
          updateProjectV2ItemFieldValue(
            input:{
              projectId:$projectId,
              itemId:$itemId,
              fieldId:$fieldId,
              value:{singleSelectOptionId:$optId}
            }
          ) { projectV2Item { id } }
        }
        """
        self.gql.run(
            mutation,
            {
                "projectId": project_id,
                "itemId": item_id,
                "fieldId": status_field.id,
                "optId": opt_id,
            },
        )
        log.info(f"[github] set Status='{status_value}' on item={item_id}")

    def update_issue_labels(self, issue_number: int, labels: list[str]) -> None:
        if not self.repo:
            raise ValueError("repo is required for update_issue_labels")

        owner, name = _split_repo(self.repo)

        if isinstance(labels, str):
            labels = [l.strip() for l in labels.split(",") if l.strip()]
        elif isinstance(labels, (int, float)):
            labels = [str(labels)]
        elif isinstance(labels, list):
            labels = [str(l).strip() for l in labels if str(l).strip()]
        else:
            labels = [str(labels).strip()]

        if not labels:
            log.info(f"[github] no labels to update for issue #{issue_number}")
            return

        log.info(f"[github] ensuring labels exist for issue #{issue_number}: {labels}")
        self._ensure_labels_exist(labels)

        r = self.http.patch(
            f"/repos/{owner}/{name}/issues/{issue_number}",
            json={"labels": labels},
        )
        applied_labels = [lbl.get("name") for lbl in r.json().get("labels", [])]
        log.info(f"[github] updated labels for issue #{issue_number}: {applied_labels}")

    def list_issues(self, page: int = 1, per_page: int = 50, state: str = "all") -> list[dict[str, Any]]:
        owner, name = _split_repo(self.repo)
        r = self.http.get(f"/repos/{owner}/{name}/issues", params={"state": state, "per_page": per_page, "page": page})
        return r.json() or []

    def purge_issue(self, _issue_node_id: str | None, number: int) -> bool:
        log.info(f"[github] Soft-deleting issue #{number}")

        try:
            self.http.patch(f"/repos/{self.repo}/issues/{number}", json={"state": "closed"})
            log.debug(f"[github] issue #{number} closed")

            self.http.put(f"/repos/{self.repo}/issues/{number}/lock")
            log.debug(f"[github] issue #{number} locked")

            return True
        except Exception as e:
            log.warning(f"[github] Soft delete failed for #{number}: {e}")
            return False


    def find_project_item(self, project_title: str, issue_node_id: str, project_id: str | None = None) -> Optional[dict]:
        project_id = project_id or self.ensure_project(project_title)
        if project_id in self._project_items_cache:
            return self._project_items_cache[project_id].get(issue_node_id)

        query = """
        query($projectId: ID!, $first: Int!, $after: String) {
        node(id: $projectId) {
            ... on ProjectV2 {
            items(first: $first, after: $after) {
                nodes {
                id
                content {
                    ... on Issue { id }
                    ... on PullRequest { id }
                }
                }
                pageInfo {
                hasNextPage
                endCursor
                }
            }
            }
        }
        }
        """

        after = None
        by_content_id: dict[str, dict] = {}
        while True:
            data = self.gql.run(query, {
                "projectId": project_id,
                "first": 100,
                "after": after,
            })

            items = (data or {}).get("node", {}).get("items") or {}
            nodes = items.get("nodes") or []

            for item in nodes:
                content = item.get("content") or {}
                content_id = content.get("id")
                if content_id:
                    by_content_id[content_id] = item

            page_info = items.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break

            after = page_info.get("endCursor")

        self._project_items_cache[project_id] = by_content_id
        return by_content_id.get(issue_node_id)
