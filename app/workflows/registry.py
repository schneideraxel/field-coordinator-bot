# app/workflows/registry.py
# Registry stub to resolve workflows from CSV or in-memory maps
from __future__ import annotations
from typing import Dict, Any

class WorkflowRegistry:
    def __init__(self):
        self._maps: Dict[str, Any] = {}
    def register(self, name: str, spec: Any) -> None:
        self._maps[name] = spec
    def get(self, name: str) -> Any:
        return self._maps.get(name)
