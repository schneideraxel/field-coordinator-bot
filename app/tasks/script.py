# app/tasks/script.py
# Tasks to run scripts
# AS 🐚🫧🪼🪸
# 21.04.2026

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from app.tasks.base import BaseTask, TaskRegistry
from app.core.context import TaskContext, WorkflowAbortError
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


def _decode_bytes(data: Optional[bytes]) -> str:
    if not data:
        return ""

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="surrogateescape")


@TaskRegistry.register("script")
@TaskRegistry.register("run_script")
class ScriptTask(BaseTask):
    def run(self, ctx: TaskContext) -> None:
        opts = [o.lower() for o in (self.params.get("options") or [])]
        continue_on_error = "continue_on_error" in opts
        script = self.params.get("script")
        if not script:
            ctx.log("[ScriptTask] Missing 'script' parameter")
            if not continue_on_error:
                raise WorkflowAbortError("[ScriptTask] missing 'script' parameter")
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
            if not continue_on_error:
                raise WorkflowAbortError(f"[ScriptTask] script not found: {script_path}")
            return

        cmd = build_command(script_path)

        output_fd, output_file = tempfile.mkstemp(suffix=".json")
        os.close(output_fd)

        env = os.environ.copy()
        env["OUTPUT_FILE"] = output_file

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=False,
                check=False,
                env=env,
            )
        except Exception as e:
            ctx.log(f"[ScriptTask] ERROR launching script: {e}")
            Path(output_file).unlink(missing_ok=True)
            if not continue_on_error:
                raise WorkflowAbortError(f"[ScriptTask] error launching script {script_path}: {e}") from e
            return

        stdout = _decode_bytes(result.stdout)
        stderr = _decode_bytes(result.stderr)

        output_key = (self.params.get("output_key") or "").strip()
        output_path = Path(output_file)
        if output_path.exists():
            content = output_path.read_text(encoding="utf-8").strip()
            if content:
                ctx.results[output_key if output_key else "script_output"] = content
            output_path.unlink(missing_ok=True)

        ctx.results["script_log"] = stdout.strip()
        ctx.results["script_error"] = stderr.strip()
        ctx.results["script_returncode"] = result.returncode

        ctx.log(f"[ScriptTask] Return code: {result.returncode}")

        if stdout:
            ctx.log(f"[ScriptTask][stdout]\n{stdout}")

        if stderr:
            ctx.log(f"[ScriptTask][stderr]\n{stderr}")

        if result.returncode != 0 and not continue_on_error:
            raise WorkflowAbortError(
                f"[ScriptTask] script exited with code {result.returncode}: {script_path}"
            )
