from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Deque, Dict, List, Optional


@dataclass(slots=True)
class PerfEntry:
    ts_iso: str
    kind: str
    name: str
    method: Optional[str]
    status_code: Optional[int]
    duration_ms: float


_MAX_ENTRIES = 5000
_entries: Deque[PerfEntry] = deque(maxlen=_MAX_ENTRIES)
_lock = Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_endpoint(*, method: str, path: str, status_code: int, duration_ms: float) -> None:
    entry = PerfEntry(
        ts_iso=_utc_now_iso(),
        kind="endpoint",
        name=str(path or ""),
        method=str(method or "").upper(),
        status_code=int(status_code),
        duration_ms=float(duration_ms),
    )
    with _lock:
        _entries.append(entry)


def record_operation(*, name: str, duration_ms: float) -> None:
    entry = PerfEntry(
        ts_iso=_utc_now_iso(),
        kind="operation",
        name=str(name or ""),
        method=None,
        status_code=None,
        duration_ms=float(duration_ms),
    )
    with _lock:
        _entries.append(entry)


def _percentile(sorted_values: List[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    idx = int(round((len(sorted_values) - 1) * p))
    idx = max(0, min(idx, len(sorted_values) - 1))
    return float(sorted_values[idx])


def top_slowest(*, kind: Optional[str] = None, limit: int = 5) -> List[Dict[str, object]]:
    grouped: Dict[str, List[PerfEntry]] = {}
    with _lock:
        snapshot = list(_entries)

    for item in snapshot:
        if kind and item.kind != kind:
            continue
        key = f"{item.method} {item.name}".strip() if item.method else item.name
        grouped.setdefault(key, []).append(item)

    rows: List[Dict[str, object]] = []
    for key, items in grouped.items():
        values = [float(x.duration_ms) for x in items]
        values_sorted = sorted(values)
        total = float(sum(values))
        count = len(values_sorted)
        rows.append(
            {
                "name": key,
                "count": count,
                "avg_ms": round(total / count, 2),
                "p95_ms": round(_percentile(values_sorted, 0.95), 2),
                "max_ms": round(max(values_sorted), 2),
                "last_ts": items[-1].ts_iso,
            }
        )

    rows.sort(key=lambda x: (float(x["avg_ms"]), float(x["max_ms"])), reverse=True)
    return rows[: max(1, int(limit))]


def recent(*, limit: int = 100, kind: Optional[str] = None) -> List[Dict[str, object]]:
    with _lock:
        snapshot = list(_entries)
    if kind:
        snapshot = [x for x in snapshot if x.kind == kind]
    tail = snapshot[-max(1, int(limit)) :]
    return [
        {
            "ts": item.ts_iso,
            "kind": item.kind,
            "name": item.name,
            "method": item.method,
            "status_code": item.status_code,
            "duration_ms": round(float(item.duration_ms), 2),
        }
        for item in tail
    ]

