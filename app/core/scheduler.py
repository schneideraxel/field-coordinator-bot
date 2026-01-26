# app/core/scheduler.py
# APScheduler wrapper for recurring workflows
# AS 🐚🫧🪼🪸
# 22.01.2026 (Last update)

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logging import get_logger
from app.workflows.engine import CSVPlanner, WorkflowEngine, TaskEngine

log = get_logger(__name__)

@dataclass
class ScheduledJobSpec:
    id: str
    csv: str
    workflow: str
    payload: Dict[str, Any]

_scheduler: Optional[BackgroundScheduler] = None
_job_locks: dict[str, threading.Lock] = {}

def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
        log.info("[scheduler] started")
    return _scheduler

def _get_job_lock(job_id: str) -> threading.Lock:
    if job_id not in _job_locks:
        _job_locks[job_id] = threading.Lock()
    return _job_locks[job_id]

def _run_workflow(csv: str, workflow: str, payload: Dict[str, Any], job_id: str) -> None:
    lock = _get_job_lock(job_id)

    if not lock.acquire(blocking=False):
        log.warning(f"[scheduler] job {job_id} is already running; skipping this run")
        return

    try:
        log.info(f"[scheduler] running job={job_id} workflow={workflow} csv={csv}")
        planner = CSVPlanner(csv)
        wf = WorkflowEngine(planner)
        tasks = wf.build_tasks(None, payload, workflow=workflow)
        engine = TaskEngine()
        engine.run(tasks, payload)
    finally:
        lock.release()

def schedule_every(job_id: str, csv: str, workflow: str, payload: Dict[str, Any], every: str) -> str:
    unit = every[-1]
    qty = int(every[:-1])
    kwargs = (
        {"seconds": qty} if unit == "s"
        else {"minutes": qty} if unit == "m"
        else {"hours": qty} if unit == "h"
        else {"days": qty}
    )

    trigger = IntervalTrigger(**kwargs)

    get_scheduler().add_job(
        _run_workflow,
        trigger=trigger,
        id=job_id,
        replace_existing=True,
        kwargs={
            "csv": csv,
            "workflow": workflow,
            "payload": payload,
            "job_id": job_id,
        },
        misfire_grace_time=300,
        coalesce=True,
    )

    log.info(f"[scheduler] scheduled every {every}: id={job_id}")
    return job_id

def schedule_cron(job_id: str, csv: str, workflow: str, payload: Dict[str, Any], cron_expr: str) -> str:
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError("cron expression must have 5 fields: 'm h dom mon dow'")

    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
    )

    get_scheduler().add_job(
        _run_workflow,
        trigger=trigger,
        id=job_id,
        replace_existing=True,
        kwargs={
            "csv": csv,
            "workflow": workflow,
            "payload": payload,
            "job_id": job_id,
        },
        misfire_grace_time=300,
        coalesce=True,
    )

    log.info(f"[scheduler] scheduled cron {cron_expr}: id={job_id}")
    return job_id

def list_jobs() -> list[dict]:
    jobs = []
    for j in get_scheduler().get_jobs():
        jobs.append({
            "id": j.id,
            "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
            "trigger": str(j.trigger),
        })
    return jobs

def cancel_job(job_id: str) -> bool:
    try:
        get_scheduler().remove_job(job_id)
        _job_locks.pop(job_id, None)
        log.info(f"[scheduler] cancelled id={job_id}")
        return True
    except Exception:
        return False
