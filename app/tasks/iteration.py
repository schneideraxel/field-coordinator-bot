# app/tasks/iteration.py
# Iteration and row-processing tasks
# AS 🐚🫧🪼🪸
# 21.04.2026

from __future__ import annotations

import json
import os
from pathlib import Path

from app.tasks.base import BaseTask, TaskRegistry
from app.core.context import TaskContext

_planner_cache: dict[str, "CSVPlanner"] = {}  # type: ignore[name-defined]


def _get_planner(csv_path: str):
    from app.workflows.engine import CSVPlanner
    if csv_path not in _planner_cache:
        _planner_cache[csv_path] = CSVPlanner(Path(csv_path))
    return _planner_cache[csv_path]


@TaskRegistry.register("foreach_rows")
class ForEachRowsTask(BaseTask):
    def run(self, context: TaskContext) -> None:
        rows = []
        log_text = context.results.get("script_output") or context.results.get("script_log", "")

        if log_text:
            try:
                rows = json.loads(log_text)
            except Exception as e:
                context.log(f"[foreach_rows] ERROR parsing JSON from script log: {e}")
                rows = []

        if not rows:
            rows = context.payload.get("rows") or []

        sub_wf = self.params.get("sub_workflow") or self.params.get("workflow")
        max_rows = int(self.params.get("max_rows", 0) or 0)
        opts = [o.lower() for o in (self.params.get("options") or [])]

        if not rows:
            if "require_rows" in opts:
                raise RuntimeError(f"[foreach_rows] no rows found but require_rows is set (sub_workflow={sub_wf})")
            context.log("[foreach_rows] no rows found")
            return
        if not sub_wf:
            context.log("[foreach_rows] no sub_workflow provided")
            return

        csv_path = self.params.get("csv") or os.environ.get("WORKFLOW_CSV")
        if not csv_path:
            raise RuntimeError(
                "foreach_rows requires a workflow CSV path (param 'csv' or env WORKFLOW_CSV)"
            )

        from app.workflows.engine import WorkflowEngine, TaskEngine

        planner = _get_planner(csv_path)
        wf = WorkflowEngine(planner)
        engine = TaskEngine()

        total = len(rows)
        if max_rows and total > max_rows:
            context.log(
                f"[foreach_rows] truncating {total} rows to max_rows={max_rows}"
            )
            rows = rows[:max_rows]
            total = len(rows)

        for i, row in enumerate(rows, 1):
            context.log(f"[foreach_rows] {i}/{total} -> {sub_wf}")
            tasks = wf.build_tasks(None, row, workflow=sub_wf)
            engine.run(tasks, row, debug=context.debug, shared={})
