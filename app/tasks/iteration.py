# app/tasks/iteration.py
# Iteration and row-processing tasks
# AS 🐚🫧🪼🪸
# 21.04.2026

from __future__ import annotations

import concurrent.futures
import json
import os
from typing import Any

from app.tasks.base import BaseTask, TaskRegistry
from app.core.context import TaskContext

_planner_cache: dict[str, Any] = {}


def _get_planner(path: str):
    from app.workflows.engine import load_planner
    if path not in _planner_cache:
        _planner_cache[path] = load_planner(path)
    return _planner_cache[path]


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

        csv_path = self.params.get("csv") or os.environ.get("WORKFLOW_FILE") or os.environ.get("WORKFLOW_CSV")
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

        max_workers = int(self.params.get("max_workers", 0) or os.environ.get("MAX_INFLIGHT", 0) or 0)
        parallel = "parallel" in opts and max_workers > 0

        if parallel:
            def _run_row(row: dict) -> list[str]:
                row_tasks = wf.build_tasks(None, row, workflow=sub_wf)
                result = engine.run(row_tasks, row, debug=context.debug, shared={})
                return result["summary"]["logs"]

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_run_row, row): i for i, row in enumerate(rows, 1)}
                for future in concurrent.futures.as_completed(futures):
                    i = futures[future]
                    try:
                        for line in future.result():
                            context.logs.append(line)
                    except Exception as e:
                        context.log(f"[foreach_rows] ERROR in row {i}: {e}")
                        if context.debug:
                            raise
        else:
            for i, row in enumerate(rows, 1):
                context.log(f"[foreach_rows] {i}/{total} -> {sub_wf}")
                tasks = wf.build_tasks(None, row, workflow=sub_wf)
                engine.run(tasks, row, debug=context.debug, shared={})
