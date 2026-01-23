# run.py
# Entrypoint for server and CLI 
# AS 🐚🫧🪼🪸
# 22.01.2026 (Last update)

from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
env_file = ROOT / ".env.local"

if env_file.exists():
    load_dotenv(env_file)
else:
    print(f"[env] WARNING: {env_file} not found")

def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"server", "serve"}:
        import uvicorn

        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "8000"))
        reload = os.getenv("UVICORN_RELOAD", "0") in ("1", "true", "True")
        uvicorn.run("app.interfaces.http.server:app", host=host, port=port, reload=reload)
        return 0

    from app.cli.cli import app as typer_app
    return typer_app()


if __name__ == "__main__":
    raise SystemExit(main())
