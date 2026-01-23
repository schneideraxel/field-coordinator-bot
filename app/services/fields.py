# app/services/fields.py

# app/services/fields.py
# FieldResolver: normalize/ensure fields & options, batched field updates
# AS 🐚🫧🪼🪸
# 12.08.2025 (Last update)

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from app.adapters.github.graphql import GraphQLClient
from app.core.caches import TTLCache
from app.core.logging import get_logger

logger = get_logger(__name__)


class FieldResolver:
    """Centralized field handling for ProjectV2 fields and values."""
    def __init__(self, gql: GraphQLClient, project_id: str, ttl_cache: Optional[TTLCache] = None):
        self.gql = gql
        self.project_id = project_id
        self.cache = ttl_cache or TTLCache(ttl_seconds=300)

    @staticmethod
    def normalize_name(raw: str) -> str:
        n = (raw or "").strip()
        if n.lower().startswith("field_"):
            n = n.split("_", 1)[1]
        # remove type hints like DATE_, NUMBER_, TEXT_, SELECT_
        parts = n.split("_", 1)
        if len(parts) == 2 and parts[0].upper() in ("DATE", "NUMBER", "TEXT", "SELECT", "SINGLE", "SINGLESELECT", "SINGLE-SELECT"):
            n = parts[1]
        return n.replace("_", " ").strip()

    def _fetch_fields(self) -> Dict[str, Dict[str, Any]]:
        cached = self.cache.get(("fields", self.project_id))
        if cached:
            return cached
        data = self.gql.execute(
            """
            query($pid:ID!){
              node(id:$pid){
                ... on ProjectV2 {
                  fields(first:100){
                    nodes {
                      ... on ProjectV2FieldCommon { id name dataType }
                      ... on ProjectV2SingleSelectField { id name dataType options { id name } }
                    }
                  }
                }
              }
            }
            """,
            {"pid": self.project_id},
            operation_name="ProjectFields",
        )
        fields = {}
        for f in data.get("node", {}).get("fields", {}).get("nodes", []):
            fields[f["name"].strip().lower()] = f
        self.cache.set(("fields", self.project_id), fields)
        return fields

    def _ensure_field(self, name: str, data_type: str) -> Dict[str, Any]:
        norm = name.strip().lower()
        fields = self._fetch_fields()
        if norm in fields:
            return fields[norm]
        data = self.gql.execute(
            """
            mutation($pid:ID!, $name:String!, $type:ProjectV2CustomFieldType!){
              createProjectV2Field(input:{projectId:$pid, dataType:$type, name:$name}){
                projectV2Field { ... on ProjectV2FieldCommon { id name dataType } }
              }
            }
            """,
            {"pid": self.project_id, "name": name, "type": data_type},
            operation_name="CreateProjectField",
        )
        created = data["createProjectV2Field"]["projectV2Field"]
        # Invalidate cache then refetch lazily
        self.cache.set(("fields", self.project_id), None)
        return created

    def ensure_single_select_option(self, field_id: str, label: str) -> str:
        data = self.gql.execute(
            """
            query($pid:ID!, $fid:ID!){
              node(id:$pid){
                ... on ProjectV2 {
                  field(id:$fid){
                    ... on ProjectV2SingleSelectField { id name options { id name } }
                  }
                }
              }
            }
            """,
            {"pid": self.project_id, "fid": field_id},
            operation_name="SingleSelectOptions",
        )
        opts = data.get("node", {}).get("field", {}).get("options", []) or []
        for o in opts:
            if o["name"].strip().lower() == label.strip().lower():
                return o["id"]
        data = self.gql.execute(
            """
            mutation($fid:ID!, $label:String!){
              createProjectV2SingleSelectFieldOption(input:{fieldId:$fid, name:$label}){
                projectV2SingleSelectFieldOption { id name }
              }
            }
            """,
            {"fid": field_id, "label": label},
            operation_name="CreateSelectOption",
        )
        return data["createProjectV2SingleSelectFieldOption"]["projectV2SingleSelectFieldOption"]["id"]

    def prepare_update_input(self, field_key: str, value: Any) -> Tuple[str, Dict[str, Any]]:
        """Return (field_id, typed_value) for updateProjectV2ItemFieldValue."""
        key = (field_key or "").strip()
        upper = key.upper()
        if upper.startswith("FIELD_"):
            key = key.split("_", 1)[1]
        hint = None
        if "_" in key:
            maybe, rest = key.split("_", 1)
            if maybe.upper() in ("DATE", "NUMBER", "TEXT", "SELECT"):
                hint, key = maybe.upper(), rest
        name = self.normalize_name(key)
        fields = self._fetch_fields()
        f = fields.get(name.lower())
        if not f:
            dtype = {"DATE": "DATE", "NUMBER": "NUMBER", "TEXT": "TEXT", "SELECT": "SINGLE_SELECT"}.get(hint or "TEXT", "TEXT")
            f = self._ensure_field(name, dtype)
            fields = self._fetch_fields()
            f = fields.get(name.lower(), f)
        field_id = f["id"]
        dtype = f.get("dataType") or "TEXT"
        if dtype == "SINGLE_SELECT":
            opt_id = self.ensure_single_select_option(field_id, str(value))
            return field_id, {"singleSelectOptionId": opt_id}
        if dtype == "NUMBER":
            return field_id, {"number": float(value)}
        if dtype == "DATE":
            return field_id, {"date": str(value)}
        return field_id, {"text": str(value)}

    def update_item_fields(self, project_id: str, item_id: str, updates: Dict[str, Any]) -> None:
        """Batch update fields via GraphQL aliasing (one request for many fields)."""
        alias_lines = []
        variables = {"pid": project_id, "item": item_id}
        var_defs = ["$pid:ID!", "$item:ID!"]
        idx = 0
        for k, v in updates.items():
            field_id, typed_value = self.prepare_update_input(k, v)
            idx += 1
            alias = f"u{idx}"
            var_f = f"$f{idx}:ID!"
            var_defs.append(var_f)
            variables[f"f{idx}"] = field_id
            alias_lines.append(
                f"""{alias}: updateProjectV2ItemFieldValue(input:{{projectId:$pid,itemId:$item,fieldId:$f{idx},value:{json.dumps(typed_value)} }}){{ projectV2Item {{ id }} }}"""
            )
        if not alias_lines:
            return
        mutation = "mutation UpdateMany(" + ", ".join(var_defs) + "){\n  " + "\n  ".join(alias_lines) + "\n}"
        self.gql.execute(mutation, variables, operation_name="UpdateManyFields")

