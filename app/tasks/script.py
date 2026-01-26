# app/tasks/script.py
# Tasks to run scripts
# AS 🐚🫧🪼🪸
# 26.01.2026

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.tasks.base import BaseTask, TaskRegistry
from app.core.context import TaskContext
from app.core.logging import get_logger

log = get_logger(__name__)


def build_command(script_path: Path) -> list[str]:
    ext = script_path.suffix.lower()

    if ext == ".r":
        r_exe = os.environ.get("RSCRIPT_EXE") or "Rscript"
        return [r_exe, str(script_path)]

    if ext == ".py":
        return ["python", str(script_path)]

    if ext in {".sh", ".bash"}:
        return ["bash", str(script_path)]

    if ext == ".pl":
        return ["perl", str(script_path)]

    if ext == ".js":
        return ["node", str(script_path)]

    if ext == ".scala":
        return ["scala", str(script_path)]

    if ext == ".jl":
        return ["julia", str(script_path)]

    if ext == ".m":
        return ["octave", "--quiet", "--eval", f"run('{script_path}')"]

    if ext == ".sas":
        return ["sas", str(script_path)]

    if ext == ".sql":
        return ["sqlite3", str(script_path)]

    if ext == ".do":
        return ["stata-mp", "-b", "do", str(script_path)]

    return [str(script_path)]



@TaskRegistry.register("script")
@TaskRegistry.register("run_script")
class ScriptTask(BaseTask):
    def run(self, ctx: TaskContext) -> None:
        script = self.params.get("script")
        if not script:
            ctx.log("[ScriptTask] Missing 'script' parameter")
            return

        repo_root = Path(__file__).resolve().parents[2]
        cwd = Path(self.params.get("cwd") or repo_root)

        script_path = Path(script)
        if not script_path.is_absolute():
            r_root = os.environ.get("R_WORKSPACE_ROOT")
            if r_root:
                script_path = Path(r_root) / script_path
            else:
                script_path = cwd / script_path

        script_path = script_path.resolve()

        if script_path.suffix.lower() == ".r":
            r_root = os.environ.get("R_WORKSPACE_ROOT")
            if r_root:
                cwd = Path(r_root)

        ctx.log(f"[ScriptTask] Running: {script_path} (cwd={cwd})")

        if not script_path.exists():
            ctx.log(f"[ScriptTask] ERROR: script not found at {script_path}")
            return

        cmd = build_command(script_path)

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                check=False,
            )
        except Exception as e:
            ctx.log(f"[ScriptTask] ERROR launching script: {e}")
            if ctx.debug:
                raise
            return

        ctx.results["script_log"] = (result.stdout or "").strip()
        ctx.results["script_error"] = (result.stderr or "").strip()
        ctx.results["script_returncode"] = result.returncode

        ctx.log(f"[ScriptTask] Return code: {result.returncode}")
        if result.stdout:
            ctx.log(f"[ScriptTask][stdout]\n{result.stdout}")
        if result.stderr:
            ctx.log(f"[ScriptTask][stderr]\n{result.stderr}")
