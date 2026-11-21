"""Tiny in-process counters exposed at /metrics (Prometheus text format)."""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_c: dict[str, float] = {}
START = time.time()


def inc(name: str, n: float = 1) -> None:
    with _lock:
        _c[name] = _c.get(name, 0) + n


def observe(name: str, value: float) -> None:
    inc(name + "_sum", value)
    inc(name + "_count", 1)


def render(extra: dict | None = None) -> str:
    with _lock:
        data = dict(_c)
    data["uptime_seconds"] = time.time() - START
    data.update(extra or {})
    return "".join(f"posterbot_{k} {v:g}\n" for k, v in sorted(data.items()))
