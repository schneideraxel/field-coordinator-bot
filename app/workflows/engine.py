# app/workflows/engine.py
# Interpret workflows and distribute tasks
# AS 🐚🫧🪼🪸
# 14.09.2025 (Last update)

from __future__ import annotations

from collections import deque
from typing import Any, Dict, Iterable, List, Tuple
import csv
from pathlib import Path

from app.tasks.base import TaskRegistry
from app.core.context import TaskContext
from app.core.utils import safe_format

_RECENT_RUNS: deque = deque(maxlen=50)

def _split_options(val: Any) -> list[str]:
    if not val:
        return []
    if isinstance(val, str):
        return [o for o in val.split() if o.strip()]
    if isinstance(val, (list, tuple)):
        return [str(o).strip() for o in val if str(o).strip()]
    return [str(val).strip()]

def _clean_params(row: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for k, v in row.items():
        if v in (None, ""):
            continue
        if k.lower() in ("workflow", "macro", "action", "task_order"):
            continue

        formatted = safe_format(v, payload)
        if k.lower() == "options":
            params["options"] = _split_options(formatted)
        else:
            params[k] = formatted
    return params

class CSVPlanner:
    def __init__(self, csv_path: str):
        self.path = Path(csv_path)
        self.rows = []
        with self.path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.rows.append(row)

    def plan(self, payload: Dict[str, Any], workflow: str | None = None) -> List[Tuple[str, Dict[str, Any]]]:
        wf = workflow or payload.get("workflow")
        if not wf:
            raise ValueError("No workflow specified (payload.workflow or --workflow)")
        rows: list[tuple[int, str, Dict[str, Any]]] = []
        for row in self.rows:
            name = row.get("workflow")
            if name != wf:
                continue
            action = (row.get("action") or "").strip()
            if not action:
                continue
            order_str = row.get("task_order") or "0"
            try:
                order = int(order_str)
            except Exception:
                order = 0
            params = _clean_params(row, payload)
            rows.append((order, action, params))
        rows.sort(key=lambda t: t[0])
        return [(action, params) for _, action, params in rows]

    def plan_by_run(self, data: dict, run: str) -> list[tuple[str, dict]]:
        matched = [r for r in self.rows if str(r.get("macro", "")).strip().lower() == run.lower()]
        if not matched:
            raise ValueError(f"No workflow found for '{run}'")

        primary = next((r for r in matched if not (r.get("sub_workflow") or "").strip()), matched[0])
        workflow = primary.get("workflow")
        if not workflow:
            raise ValueError(f"No primary workflow found for '{run}'")

        payload = dict(data)
        if primary.get("source"):
            payload["__source__"] = safe_format(primary["source"], data)
        payload["workflow"] = workflow

        return self.plan(payload)

class WorkflowEngine:
    def __init__(self, planner: CSVPlanner):
        self.planner = planner

    def build_tasks(self, _registry: Dict[str, Any] | None, payload: Dict[str, Any], workflow: str | None = None) -> List[Tuple[str, Dict[str, Any]]]:
        return self.planner.plan(payload, workflow=workflow)

class TaskEngine:
    def run(
        self,
        tasks: Iterable[Tuple[str, Dict[str, Any]]],
        payload: Dict[str, Any],
        debug: bool = False,
    ) -> Dict[str, Any]:
        ctx = TaskContext(payload=dict(payload), debug=debug)
        ctx.log(f"[TaskEngine] planned tasks: {[t[0] for t in tasks]}")

        for task_name, params in tasks:
            task_cls = TaskRegistry.get(task_name)
            if not task_cls:
                ctx.log(f"[TaskEngine] WARNING: Unknown task '{task_name}'; skipping")
                continue

            options = params.get("options", [])
            ctx.log(f"[TaskEngine] task={task_name} resolved options={options}")

            task = task_cls(params={**params, "options": options})

            try:
                task.run(ctx)
            except Exception as e:
                ctx.log(f"[TaskEngine] ERROR in {task_name}: {e}")
                if debug:
                    raise

        summary = {
            "payload": ctx.payload,
            "results": dict(ctx.results),
            "logs": list(ctx.logs),
        }
        _RECENT_RUNS.appendleft(summary)
        return {"context": ctx, "summary": summary}


def get_recent_runs() -> List[Dict[str, Any]]:
    return list(_RECENT_RUNS)
