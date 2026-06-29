# app/cli/cli.py
# Typer CLI: run workflows, schedule, list workflows, list jobs, cancel, list tasks
# AS 🐚🫧🪼🪸
# 22.01.2026

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import typer
import requests

from app.core.logging import get_logger
from app.workflows.engine import load_planner, WorkflowEngine, TaskEngine
from app.tasks.base import TaskRegistry
import app.tasks

log = get_logger(__name__)
app = typer.Typer(add_completion=False, help="Field Coordinator Bot CLI")

DEFAULT_CSV = os.getenv("WORKFLOW_FILE") or os.getenv("WORKFLOW_CSV", "workflows/workflows.yaml")
SCHEDULER_URL = os.getenv("SCHEDULER_URL", "http://127.0.0.1:8000")


def _load_payload(s: str) -> Dict[str, Any]:
    p = Path(s)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return json.loads(s)


@app.command("run")
def run_payload(
    payload: str = typer.Argument(..., help="Path to JSON payload or inline JSON"),
    csv: str = typer.Option(DEFAULT_CSV, "--csv", help="Workflow CSV path"),
    workflow: Optional[str] = typer.Option(
        None, "--workflow", "-w", help="Workflow name (defaults to payload.workflow)"
    ),
    debug: bool = typer.Option(False, "--debug", help="Raise on task error"),
):
    data = _load_payload(payload)
    planner = load_planner(csv)
    wf = WorkflowEngine(planner)
    tasks = wf.build_tasks(None, data, workflow=workflow)
    engine = TaskEngine()
    result = engine.run(tasks, data, debug=debug)
    typer.echo(json.dumps(result["summary"], ensure_ascii=False))


@app.command("workflow")
def run_workflow(
    run_name: str = typer.Argument(..., help="Workflow macro name"),
    payload: Optional[str] = typer.Argument(
        None, help="Path to JSON payload or inline JSON"
    ),
    csv: str = typer.Option(DEFAULT_CSV, "--csv", help="Workflow CSV path"),
    debug: bool = typer.Option(False, "--debug", help="Raise on task error"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print planned tasks without executing"
    ),
):
    data: Dict[str, Any] = {}
    if payload:
        data = _load_payload(payload)

    try:
        planner = load_planner(csv)
        tasks = planner.plan_by_run(data, run_name)
        payload = planner.get_effective_payload(data, run_name)

        if dry_run:
            for i, (action, params) in enumerate(tasks, start=1):
                typer.echo(f"{i:02d}. {action}  {params}")
            return

        engine = TaskEngine()
        result = engine.run(tasks, payload, debug=debug)
        typer.echo(json.dumps(result["summary"], ensure_ascii=False))

    except ValueError as ve:
        typer.echo(f"ERROR: {ve}")
        raise typer.Exit(code=1)


@app.command("list-workflows")
def list_workflows(
    csv: str = typer.Option(DEFAULT_CSV, "--csv", help="Workflow CSV path")
):
    planner = load_planner(csv)
    for name in planner.workflow_names:
        typer.echo(name)


@app.command("list-tasks")
def list_tasks():
    names = sorted(TaskRegistry.all().keys())
    for n in names:
        typer.echo(n)


@app.command("schedule")
def schedule(
    job_id: str = typer.Option(..., "--id", "-i", help="Job ID"),
    payload: str = typer.Option("{}", "--payload", "-p", help="Path or inline JSON"),
    csv: str = typer.Option(DEFAULT_CSV, "--csv", help="Workflow CSV path"),
    workflow: str = typer.Option(..., "--workflow", "-w", help="Workflow name to run"),
    every: Optional[str] = typer.Option(None, "--every", help="Interval like 5m, 1h, 30s"),
    cron: Optional[str] = typer.Option(
        None, "--cron", help="Cron 'm h dom mon dow' like '0 9 * * *'"
    ),
):
    data = _load_payload(payload)

    if every and cron:
        raise typer.BadParameter("Use either --every or --cron, not both.")

    body = {
        "id": job_id,
        "workflow": workflow,
        "payload": data,
        "csv": csv,
    }

    if every:
        resp = requests.post(
            f"{SCHEDULER_URL}/schedule/every",
            json={**body, "every": every},
        )
    elif cron:
        resp = requests.post(
            f"{SCHEDULER_URL}/schedule/cron",
            json={**body, "cron": cron},
        )
    else:
        raise typer.BadParameter("Provide --every or --cron")

    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = resp.text
        typer.echo(f"ERROR: {detail}")
        raise typer.Exit(code=1)

    result = resp.json()
    typer.echo(f"scheduled: {result['scheduled']}")


@app.command("list-jobs")
def list_jobs_cmd():
    resp = requests.get(f"{SCHEDULER_URL}/jobs")

    if resp.status_code != 200:
        typer.echo("ERROR: failed to list jobs")
        raise typer.Exit(code=1)

    data = resp.json()
    for j in data["jobs"]:
        typer.echo(json.dumps(j))


@app.command("cancel-job")
def cancel_job_cmd(
    job_id: str = typer.Option(..., "--id", "-i", help="Job ID")
):
    resp = requests.delete(f"{SCHEDULER_URL}/jobs/{job_id}")

    if resp.status_code != 200:
        typer.echo("ERROR: failed to cancel job")
        raise typer.Exit(code=1)

    data = resp.json()
    typer.echo("ok" if data["cancelled"] else "not-found")


@app.command("task")
def run_task(
    task_name: str = typer.Argument(..., help="Name of the registered task"),
    params: list[str] = typer.Argument(
        None,
        help=(
            "Task parameters in key=value format. "
            "Supports strings, numbers, JSON values, and 'options' as space-separated words."
        ),
    ),
    payload: Optional[str] = typer.Option(
        None,
        "--payload",
        "-p",
        help="Optional path to a JSON file or inline JSON string",
    ),
    debug: bool = typer.Option(False, "--debug", help="Raise errors instead of logging"),
):
    parsed_params: Dict[str, Any] = {}

    if params:
        for p in params:
            if "=" not in p:
                typer.echo(f"Invalid parameter: {p} (expected key=value)")
                raise typer.Exit(code=1)
            k, v = p.split("=", 1)
            v = v.strip()
            try:
                parsed_params[k] = json.loads(v)
            except Exception:
                if k == "options":
                    parsed_params[k] = v.split()
                else:
                    parsed_params[k] = v

    if payload:
        extra = _load_payload(payload)
        parsed_params.update(extra)

    task_cls = TaskRegistry.get(task_name)
    if not task_cls:
        typer.echo(f"ERROR: Unknown task '{task_name}'")
        raise typer.Exit(code=1)

    from app.core.context import TaskContext

    ctx = TaskContext(payload={}, debug=debug)
    task = task_cls(params=parsed_params)

    try:
        task.run(ctx)
    except Exception as e:
        ctx.log(f"[task] ERROR in {task_name}: {e}")
        if debug:
            raise

    typer.echo(
        json.dumps(
            {
                "task": task_name,
                "params": parsed_params,
                "results": dict(ctx.results),
                "logs": list(ctx.logs),
            },
            ensure_ascii=False,
        )
    )


def main():
    app()


if __name__ == "__main__":
    main()
