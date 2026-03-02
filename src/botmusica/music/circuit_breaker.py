from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int
    recovery_seconds: float
    half_open_max_calls: int = 1
    _state: str = "closed"
    _failures: int = 0
    _opened_at: float = 0.0
    _half_open_calls: int = 0

    def allow_request(self) -> bool:
        now = time.monotonic()
        if self._state == "closed":
            return True
        if self._state == "open":
            if (now - self._opened_at) < self.recovery_seconds:
                return False
            self._state = "half_open"
            self._half_open_calls = 0
        if self._state == "half_open":
            if self._half_open_calls >= self.half_open_max_calls:
                return False
            self._half_open_calls += 1
            return True
        return True

    def record_success(self) -> None:
        self._state = "closed"
        self._failures = 0
        self._half_open_calls = 0

    def record_failure(self) -> None:
        if self._state == "half_open":
            self._state = "open"
            self._opened_at = time.monotonic()
            self._half_open_calls = 0
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state = "open"
            self._opened_at = time.monotonic()

    @property
    def state(self) -> str:
        return self._state
