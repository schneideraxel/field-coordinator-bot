# app/core/caches.py
# Tiny thread-safe TTL cache (stdlib only)
# AS 🐚🫧🪼🪸
# 12.08.2025 (Last update)

from __future__ import annotations

import threading, time
from typing import Any, Optional


class TTLCache:
    def __init__(self, ttl_seconds: float = 300.0, maxsize: int = 1024):
        self._ttl = float(ttl_seconds)
        self._max = int(maxsize)
        self._store: dict[Any, Any] = {}
        self._exp: dict[Any, float] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Optional[Any]:
        now = time.time()
        with self._lock:
            v = self._store.get(key)
            if v is None:
                return None
            if now >= self._exp.get(key, 0):
                self._store.pop(key, None)
                self._exp.pop(key, None)
                return None
            return v

    def set(self, key: Any, value: Any) -> None:
        now = time.time()
        with self._lock:
            if key not in self._store and len(self._store) >= self._max:
                oldest = min(self._exp.items(), key=lambda kv: kv[1])[0]
                self._store.pop(oldest, None)
                self._exp.pop(oldest, None)
            self._store[key] = value
            self._exp[key] = now + self._ttl

