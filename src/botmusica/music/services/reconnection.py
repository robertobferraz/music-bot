from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    attempts: int
    base_delay_seconds: float
    max_delay_seconds: float
    jitter_ratio: float

    def backoff_schedule(self) -> list[float]:
        tries = max(self.attempts, 1)
        base = max(self.base_delay_seconds, 0.05)
        max_delay = max(self.max_delay_seconds, base)
        jitter = max(min(self.jitter_ratio, 1.0), 0.0)
        delays: list[float] = []
        for attempt in range(tries):
            delay = min(base * (2**attempt), max_delay)
            if jitter > 0:
                spread = delay * jitter
                delay = max(0.0, random.uniform(delay - spread, delay + spread))
            delays.append(delay)
        return delays
