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
from app.core.context import TaskContext, WorkflowAbortError

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
        source = (self.params.get("source") or "").strip()
        if source:
            log_text = context.results.get(source, "")
        else:
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
                enriched = {**context.payload, **row}
                row_tasks = wf.build_tasks(None, enriched, workflow=sub_wf)
                result = engine.run(row_tasks, enriched, debug=context.debug, shared={})
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
                enriched = {**context.payload, **row}
                tasks = wf.build_tasks(None, enriched, workflow=sub_wf)
                engine.run(tasks, enriched, debug=context.debug, shared={})


@TaskRegistry.register("parallel_group")
class ParallelGroupTask(BaseTask):
    def run(self, ctx: TaskContext) -> None:
        task_specs: list[tuple[str, dict]] = self.params.get("tasks") or []
        if not task_specs:
            ctx.log("[parallel_group] no tasks defined")
            return

        max_workers = int(self.params.get("max_workers", 0) or os.environ.get("MAX_INFLIGHT", 0) or len(task_specs))

        def _run_subtask(spec: tuple) -> tuple[list, dict]:
            action, params = spec
            task_cls = TaskRegistry.get(action)
            if not task_cls:
                return [f"[parallel_group] WARNING: unknown task '{action}'; skipping"], {}
            task = task_cls(params=params)
            sub_ctx = TaskContext(payload=dict(ctx.payload), debug=ctx.debug, shared_cache={})
            try:
                task.run(sub_ctx)
            except WorkflowAbortError:
                raise
            except Exception as e:
                sub_ctx.log(f"[parallel_group] ERROR: {e}")
                if ctx.debug:
                    raise
            return sub_ctx.logs, sub_ctx.results

        completed: list[tuple[int, list, dict]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_run_subtask, spec): i for i, spec in enumerate(task_specs, 1)}
            for future in concurrent.futures.as_completed(futures):
                i = futures[future]
                try:
                    logs, results = future.result()
                    completed.append((i, logs, results))
                except WorkflowAbortError:
                    raise
                except Exception as e:
                    ctx.log(f"[parallel_group] ERROR in subtask {i}: {e}")
                    if ctx.debug:
                        raise

        for _, logs, results in sorted(completed, key=lambda x: x[0]):
            ctx.logs.extend(logs)
            ctx.results.update(results)
