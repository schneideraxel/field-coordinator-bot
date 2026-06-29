# app/core/utils.py
# Safe templating + TaskResult helpers
# AS 🐚🫧🪼🪸
# 14.08.2025 (Last update)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from app.core.logging import get_logger

log = get_logger(__name__)

class SafeDict(dict):
    def __missing__(self, k):
        return "{" + str(k) + "}"

def safe_format(template: str, mapping: dict):
    try:
        return template.format_map(SafeDict(mapping))
    except Exception as e:
        log.warning(f"safe_format error on template {template!r}: {e}")
        return template

@dataclass
class TaskResult:
    ok: bool
    attempts: int = 1
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

def ok(details: Dict[str, Any] | None = None) -> TaskResult:
    return TaskResult(ok=True, details=details or {})

def fail(errs, details: Dict[str, Any] | None = None) -> TaskResult:
    return TaskResult(ok=False, errors=[errs] if isinstance(errs, str) else list(errs), details=details or {})
