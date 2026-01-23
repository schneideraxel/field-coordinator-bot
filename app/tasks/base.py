# app/tasks/base.py
# BaseTask and TaskRegistry (compat layer)
# AS 🐚🫧🪼🪸
# 14.09.2025 (Last update)

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Type

class BaseTask:
    name: str = "base"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        self.params = params or {}

    def run(self, context):
        raise NotImplementedError

    def get_options(self, ctx: "TaskContext") -> list[str]:
        raw = self.params.get("options") or ctx.payload.get("options") or []
        if isinstance(raw, str):
            return [o for o in raw.split() if o]
        return list(raw) if isinstance(raw, (list, tuple)) else []

class TaskRegistry:
    _r: Dict[str, Type[BaseTask]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[Type[BaseTask]], Type[BaseTask]]:
        def deco(task_cls: Type[BaseTask]) -> Type[BaseTask]:
            cls._r[name] = task_cls
            task_cls.name = name
            return task_cls
        return deco

    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseTask]]:
        return cls._r.get(name)

    @classmethod
    def all(cls) -> Dict[str, Type[BaseTask]]:
        return dict(cls._r)
