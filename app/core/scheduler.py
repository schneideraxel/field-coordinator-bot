# app/core/scheduler.py
# APScheduler wrapper for recurring workflows
# AS 🐚🫧🪼🪸
# 21.04.2026 (Last update)

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logging import get_logger
from app.workflows.engine import load_planner, WorkflowEngine, TaskEngine

log = get_logger(__name__)

@dataclass
class ScheduledJobSpec:
    id: str
    csv: str
    workflow: str
    payload: Dict[str, Any]
    trigger_type: str  # "every" | "cron"
    trigger_spec: str  # e.g. "5m" or "0 9 * * *"

_JOBS_FILE = Path(os.getenv("SCHEDULER_JOBS_FILE", "scheduler_jobs.json"))
_scheduler: Optional[BackgroundScheduler] = None
_job_locks: dict[str, threading.Lock] = {}


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
        log.info("[scheduler] started")
        _restore_scheduled_jobs()
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
        planner = load_planner(csv)
        wf = WorkflowEngine(planner)
        tasks = wf.build_tasks(None, payload, workflow=workflow)
        engine = TaskEngine()
        engine.run(tasks, payload)
    finally:
        lock.release()


def _parse_every(every: str) -> dict:
    unit = every[-1]
    qty = int(every[:-1])
    return (
        {"seconds": qty} if unit == "s"
        else {"minutes": qty} if unit == "m"
        else {"hours": qty} if unit == "h"
        else {"days": qty}
    )


def _parse_cron(cron_expr: str) -> dict:
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError("cron expression must have 5 fields: 'm h dom mon dow'")
    return dict(minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4])


def _add_to_scheduler(job_id: str, csv: str, workflow: str, payload: Dict[str, Any], trigger) -> None:
    get_scheduler().add_job(
        _run_workflow,
        trigger=trigger,
        id=job_id,
        replace_existing=True,
        kwargs={"csv": csv, "workflow": workflow, "payload": payload, "job_id": job_id},
        misfire_grace_time=300,
        coalesce=True,
    )


def _load_job_specs() -> list[dict]:
    if not _JOBS_FILE.exists():
        return []
    try:
        return json.loads(_JOBS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"[scheduler] could not load jobs file: {e}")
        return []


def _save_job_specs(specs: list[dict]) -> None:
    try:
        _JOBS_FILE.write_text(json.dumps(specs, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"[scheduler] could not save jobs file: {e}")


def _upsert_job_spec(spec: ScheduledJobSpec) -> None:
    specs = [s for s in _load_job_specs() if s["id"] != spec.id]
    specs.append(asdict(spec))
    _save_job_specs(specs)


def _remove_job_spec(job_id: str) -> None:
    specs = [s for s in _load_job_specs() if s["id"] != job_id]
    _save_job_specs(specs)


def _restore_scheduled_jobs() -> None:
    for raw in _load_job_specs():
        try:
            job_id = raw["id"]
            trigger_type = raw["trigger_type"]
            trigger_spec = raw["trigger_spec"]
            if trigger_type == "every":
                trigger = IntervalTrigger(**_parse_every(trigger_spec))
            elif trigger_type == "cron":
                trigger = CronTrigger(**_parse_cron(trigger_spec))
            else:
                log.warning(f"[scheduler] unknown trigger_type='{trigger_type}' for job={job_id}, skipping")
                continue
            _add_to_scheduler(job_id, raw["csv"], raw["workflow"], raw["payload"], trigger)
            log.info(f"[scheduler] restored job={job_id} ({trigger_type}: {trigger_spec})")
        except Exception as e:
            log.warning(f"[scheduler] could not restore job {raw.get('id')}: {e}")


def schedule_every(job_id: str, csv: str, workflow: str, payload: Dict[str, Any], every: str) -> str:
    trigger = IntervalTrigger(**_parse_every(every))
    _add_to_scheduler(job_id, csv, workflow, payload, trigger)
    _upsert_job_spec(ScheduledJobSpec(id=job_id, csv=csv, workflow=workflow, payload=payload, trigger_type="every", trigger_spec=every))
    log.info(f"[scheduler] scheduled every {every}: id={job_id}")
    return job_id


def schedule_cron(job_id: str, csv: str, workflow: str, payload: Dict[str, Any], cron_expr: str) -> str:
    trigger = CronTrigger(**_parse_cron(cron_expr))
    _add_to_scheduler(job_id, csv, workflow, payload, trigger)
    _upsert_job_spec(ScheduledJobSpec(id=job_id, csv=csv, workflow=workflow, payload=payload, trigger_type="cron", trigger_spec=cron_expr))
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
        _remove_job_spec(job_id)
        log.info(f"[scheduler] cancelled id={job_id}")
        return True
    except Exception:
        return False
