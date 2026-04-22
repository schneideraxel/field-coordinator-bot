# app/workflows/engine.py
# Interpret workflows and distribute tasks
# AS 🐚🫧🪼🪸
# 21.04.2026 (Last update)

from __future__ import annotations

from collections import deque
from typing import Any, Dict, Iterable, List, Tuple
import csv
from pathlib import Path

from app.tasks.base import TaskRegistry
from app.core.context import TaskContext, WorkflowAbortError
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

_REQUIRED_COLUMNS = {"workflow", "action", "task_order"}


class CSVPlanner:
    def __init__(self, csv_path: str):
        self.path = Path(csv_path)
        self.rows = []
        with self.path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.rows.append(row)
        self._validate()

    def _validate(self) -> None:
        if not self.rows:
            return
        cols = set(self.rows[0].keys())
        missing = _REQUIRED_COLUMNS - cols
        if missing:
            raise ValueError(f"CSV missing required columns: {sorted(missing)}")

        all_workflows = {row.get("workflow") for row in self.rows if row.get("workflow")}
        errors = []

        for i, row in enumerate(self.rows, start=2):
            wf = row.get("workflow", "").strip()
            action = row.get("action", "").strip()
            if not wf or not action:
                continue
            order_str = (row.get("task_order") or "").strip()
            if order_str:
                try:
                    int(order_str)
                except ValueError:
                    errors.append(f"Row {i} (workflow={wf}): task_order='{order_str}' is not an integer")
            if action == "foreach_rows":
                sub_wf = (row.get("sub_workflow") or "").strip()
                if not sub_wf:
                    errors.append(f"Row {i} (workflow={wf}): foreach_rows missing sub_workflow")
                elif sub_wf not in all_workflows:
                    errors.append(f"Row {i} (workflow={wf}): sub_workflow='{sub_wf}' not found in CSV")

        if errors:
            raise ValueError("CSV validation errors:\n" + "\n".join(f"  - {e}" for e in errors))

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

    def get_effective_payload(self, data: dict, _workflow: str) -> dict:
        return data

    @property
    def workflow_names(self) -> list[str]:
        return sorted({row["macro"] for row in self.rows if row.get("macro")})


def load_planner(path: str):
    ext = Path(path).suffix.lower()
    if ext in (".yml", ".yaml"):
        from app.workflows.yaml_planner import YAMLPlanner
        return YAMLPlanner(path)
    return CSVPlanner(path)


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
        shared: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        tasks = list(tasks)
        ctx = TaskContext(payload=dict(payload), debug=debug, shared_cache=shared if shared is not None else {})
        ctx.log(f"[TaskEngine] planned tasks: {[t[0] for t in tasks]}")

        abort_exc: WorkflowAbortError | None = None

        for task_name, params in tasks:
            task_cls = TaskRegistry.get(task_name)
            if not task_cls:
                ctx.log(f"[TaskEngine] WARNING: Unknown task '{task_name}'; skipping")
                continue

            when = (params.get("when") or "always").strip().lower()
            if when == "never":
                ctx.log(f"[TaskEngine] task={task_name} skipped (when=never)")
                continue
            elif when == "has_rows":
                source = (params.get("source") or "").strip()
                check_key = source if source else "script_output"
                has = bool(ctx.results.get(check_key) or (not source and ctx.results.get("script_log")))
                if not has:
                    ctx.log(f"[TaskEngine] task={task_name} skipped (when=has_rows, no data in '{check_key}')")
                    continue
            elif when == "no_rows":
                source = (params.get("source") or "").strip()
                check_key = source if source else "script_output"
                has = bool(ctx.results.get(check_key) or (not source and ctx.results.get("script_log")))
                if has:
                    ctx.log(f"[TaskEngine] task={task_name} skipped (when=no_rows, data present in '{check_key}')")
                    continue

            options = params.get("options", [])
            ctx.log(f"[TaskEngine] task={task_name} resolved options={options}")

            task_params = {k: v for k, v in params.items() if k != "when"}
            task = task_cls(params={**task_params, "options": options})

            try:
                task.run(ctx)
            except WorkflowAbortError as e:
                ctx.log(f"[TaskEngine] ABORT in {task_name}: {e}")
                abort_exc = e
                break
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

        if abort_exc is not None:
            raise abort_exc

        return {"context": ctx, "summary": summary}


def get_recent_runs() -> List[Dict[str, Any]]:
    return list(_RECENT_RUNS)
