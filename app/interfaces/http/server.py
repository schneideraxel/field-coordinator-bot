# app/interfaces/http/server.py
# FastAPI entrypoint
# AS 🐚🫧🪼🪸
# 22.01.2026 (Last update)

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Dict

from fastapi import FastAPI, Header, HTTPException, Request

from app.workflows.engine import TaskEngine, load_planner, WorkflowEngine, get_recent_runs
from app.tasks import github as _github_tasks
from app.tasks import script as _script_task

from app.core.scheduler import (
    get_scheduler,
    schedule_every,
    schedule_cron,
    list_jobs,
    cancel_job,
)

app = FastAPI(title="Benin Automation Service")

WORKFLOW_CSV = os.getenv("WORKFLOW_FILE") or os.getenv("WORKFLOW_CSV", "workflows/workflows.yaml")
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


@app.on_event("startup")
def _startup_scheduler():
    get_scheduler()


def _verify_signature(secret: str, body: bytes, sig256: str | None) -> None:
    if not secret:
        return
    if not sig256 or not sig256.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing or invalid signature")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig256):
        raise HTTPException(status_code=401, detail="Signature mismatch")


@app.post("/webhook")
async def webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
):
    raw = await request.body()
    _verify_signature(WEBHOOK_SECRET, raw, x_hub_signature_256)
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    planner = load_planner(WORKFLOW_CSV)
    wf = WorkflowEngine(planner)
    tasks = wf.build_tasks(None, payload)
    effective = planner.get_effective_payload(payload, payload.get("workflow", ""))
    engine = TaskEngine()
    run = engine.run(tasks, effective)
    return {"status": "ok", "event": x_github_event, "summary": run["summary"]}


@app.get("/recent")
async def recent():
    return {"runs": get_recent_runs()}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/schedule/every")
async def schedule_every_api(body: Dict[str, Any]):
    try:
        job_id = body["id"]
        workflow = body["workflow"]
        every = body["every"]
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing field: {e.args[0]}")

    csv = body.get("csv") or WORKFLOW_CSV
    payload = body.get("payload", {})

    existing_ids = {j["id"] for j in list_jobs()}
    if job_id in existing_ids:
        raise HTTPException(status_code=409, detail=f"Job already exists: {job_id}")

    schedule_every(job_id, csv, workflow, payload, every)
    return {"scheduled": job_id}


@app.post("/schedule/cron")
async def schedule_cron_api(body: Dict[str, Any]):
    try:
        job_id = body["id"]
        workflow = body["workflow"]
        cron = body["cron"]
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing field: {e.args[0]}")

    csv = body.get("csv") or WORKFLOW_CSV
    payload = body.get("payload", {})

    existing_ids = {j["id"] for j in list_jobs()}
    if job_id in existing_ids:
        raise HTTPException(status_code=409, detail=f"Job already exists: {job_id}")

    schedule_cron(job_id, csv, workflow, payload, cron)
    return {"scheduled": job_id}


@app.get("/jobs")
async def jobs_api():
    return {"jobs": list_jobs()}


@app.delete("/jobs/{job_id}")
async def cancel_job_api(job_id: str):
    ok = cancel_job(job_id)
    return {"cancelled": ok}
