# app/core/context.py
# Shared TaskContext (logs, results, helpers)
# AS 🐚🫧🪼🪸
# 14.08.2025 (Last update)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class TaskContext:
    payload: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    correlation_id: Optional[str] = None
    debug: bool = False

    def log(self, message: str) -> None:
        print(message)
        self.logs.append(message)

    def set_result(self, key: str, value: Any) -> None:
        self.results[key] = value

    def get_result(self, key: str, default: Any = None) -> Any:
        return self.results.get(key, default)

    def fork_with_payload(self, new_payload: Dict[str, Any]) -> "TaskContext":
        return TaskContext(payload=dict(new_payload), results=dict(self.results), logs=list(self.logs), correlation_id=self.correlation_id, debug=self.debug)
