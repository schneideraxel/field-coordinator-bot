# app/core/context.py
# Shared TaskContext (logs, results, helpers)
# AS 🐚🫧🪼🪸
# 21.04.2026 (Last update)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class WorkflowAbortError(RuntimeError):
    pass


@dataclass
class TaskContext:
    payload: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    correlation_id: Optional[str] = None
    debug: bool = False
    shared_cache: Dict[str, Any] = field(default_factory=dict)

    def log(self, message: str) -> None:
        print(message)
        self.logs.append(message)

    def set_result(self, key: str, value: Any) -> None:
        self.results[key] = value

    def get_result(self, key: str, default: Any = None) -> Any:
        return self.results.get(key, default)

    def get_shared(self, key: str, default: Any = None) -> Any:
        return self.shared_cache.get(key, default)

    def set_shared(self, key: str, value: Any) -> None:
        self.shared_cache[key] = value

    def fork_with_payload(self, new_payload: Dict[str, Any]) -> "TaskContext":
        return TaskContext(
            payload=dict(new_payload),
            results=dict(self.results),
            logs=list(self.logs),
            correlation_id=self.correlation_id,
            debug=self.debug,
            shared_cache=self.shared_cache,
        )
