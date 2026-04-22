# app/workflows/yaml_planner.py
# YAML-based workflow planner
# AS 🐚🫧🪼🪸
# 21.04.2026

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from app.core.utils import safe_format


def _normalize_options(val: Any) -> list[str]:
    if not val:
        return []
    if isinstance(val, str):
        return [o for o in val.split() if o.strip()]
    if isinstance(val, (list, tuple)):
        return [str(o).strip() for o in val if str(o).strip()]
    return [str(val).strip()]


def _clean_params(task_dict: dict, payload: dict) -> dict:
    params: Dict[str, Any] = {}
    for k, v in task_dict.items():
        if k == "action" or v is None or v == "":
            continue
        if isinstance(v, str):
            v = safe_format(v, payload)
        if k == "options":
            params["options"] = _normalize_options(v)
        else:
            params[k] = v
    return params


class YAMLPlanner:
    def __init__(self, yaml_path: str):
        self.path = Path(yaml_path)
        with self.path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._workflows: Dict[str, List[dict]] = {
            name: (wf_def.get("tasks") or [])
            for name, wf_def in (data.get("workflows") or {}).items()
        }
        self._validate()

    def _validate(self) -> None:
        all_names = set(self._workflows.keys())
        errors = []
        for wf_name, tasks in self._workflows.items():
            for i, task in enumerate(tasks, start=1):
                action = (task.get("action") or "").strip()
                if not action:
                    errors.append(f"Workflow '{wf_name}' task {i}: missing 'action'")
                    continue
                if action == "foreach_rows":
                    sub_wf = (task.get("sub_workflow") or "").strip()
                    if not sub_wf:
                        errors.append(f"Workflow '{wf_name}' task {i}: foreach_rows missing sub_workflow")
                    elif sub_wf not in all_names:
                        errors.append(f"Workflow '{wf_name}' task {i}: sub_workflow='{sub_wf}' not found")
        if errors:
            raise ValueError("YAML validation errors:\n" + "\n".join(f"  - {e}" for e in errors))

    def plan(self, payload: dict, workflow: str | None = None) -> List[Tuple[str, dict]]:
        wf = workflow or payload.get("workflow")
        if not wf:
            raise ValueError("No workflow specified")
        tasks = self._workflows.get(wf)
        if tasks is None:
            raise ValueError(f"Workflow '{wf}' not found")
        return [
            (task["action"], _clean_params(task, payload))
            for task in tasks
            if (task.get("action") or "").strip()
        ]

    def plan_by_run(self, data: dict, run: str) -> List[Tuple[str, dict]]:
        if run not in self._workflows:
            raise ValueError(f"No workflow found for '{run}'")
        return self.plan(data, workflow=run)

    @property
    def workflow_names(self) -> List[str]:
        return sorted(self._workflows.keys())
