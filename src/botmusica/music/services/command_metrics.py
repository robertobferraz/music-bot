from __future__ import annotations

import time
from collections import defaultdict, deque
from math import ceil


class CommandMetricsWindow:
    def __init__(self) -> None:
        self._samples: dict[str, deque[tuple[float, float]]] = defaultdict(deque)

    def add(self, command: str, latency_ms: float) -> None:
        key = (command or "unknown").strip().casefold() or "unknown"
        now = time.monotonic()
        self._samples[key].append((now, max(latency_ms, 0.0)))

    def _prune(self, key: str, window_seconds: float) -> None:
        now = time.monotonic()
        bucket = self._samples.get(key)
        if bucket is None:
            return
        while bucket and (now - bucket[0][0]) > window_seconds:
            bucket.popleft()
        if not bucket:
            self._samples.pop(key, None)

    def avg_ms(self, command: str, *, window_seconds: float = 300.0) -> float:
        key = (command or "unknown").strip().casefold() or "unknown"
        self._prune(key, window_seconds)
        bucket = self._samples.get(key)
        if not bucket:
            return 0.0
        return sum(lat for _ts, lat in bucket) / len(bucket)

    def percentile_ms(self, command: str, percentile: float, *, window_seconds: float = 300.0) -> float:
        key = (command or "unknown").strip().casefold() or "unknown"
        self._prune(key, window_seconds)
        bucket = self._samples.get(key)
        if not bucket:
            return 0.0
        values = sorted(lat for _ts, lat in bucket)
        p = max(min(percentile, 100.0), 0.0)
        if not values:
            return 0.0
        idx = max(min(ceil((p / 100.0) * len(values)) - 1, len(values) - 1), 0)
        return values[idx]

    def snapshot(self, *, window_seconds: float = 300.0) -> dict[str, float]:
        out: dict[str, float] = {}
        for key in list(self._samples.keys()):
            avg = self.avg_ms(key, window_seconds=window_seconds)
            if avg > 0:
                out[key] = avg
        return out
