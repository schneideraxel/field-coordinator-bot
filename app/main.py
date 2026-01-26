# app/main.py
# Main entrypoint: default to CLI; FastAPI served via `uvicorn app.server:app`
# AS 🐚🫧🪼🪸
# 12.08.2025 (Last update)

from __future__ import annotations

from app.cli.cli import main as cli_main

if __name__ == "__main__":
    raise SystemExit(cli_main())

