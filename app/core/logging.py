# app/core/logging.py
# Structured logger wrapper
# AS 🐚🫧🪼🪸
# 14.08.2025 (Last update)

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_JSON = os.getenv("LOG_JSON", "0") in ("1", "true", "True")

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "lvl": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter() if _JSON else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, _LEVEL, logging.INFO))
    return logger
