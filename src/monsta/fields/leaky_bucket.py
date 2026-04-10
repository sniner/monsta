from __future__ import annotations

import threading
import time
from typing import Any

from .base import Field


class LeakyBucket(Field):
    """Token-bucket rate limiter.

    The bucket drains at ``leak_rate`` tokens per second. Call
    ``request(amount=1.0)`` to consume tokens — returns ``True`` if the
    request fits, ``False`` if it would overflow capacity.

    API:
        - ``request(amount=1.0)`` — try to consume tokens
        - ``reset()``             — empty the bucket immediately
    """

    def __init__(self, capacity: float, leak_rate: float) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        if leak_rate <= 0:
            raise ValueError(f"leak_rate must be positive, got {leak_rate}")
        self.capacity = capacity
        self.leak_rate = leak_rate
        self._lock = threading.Lock()
        self._level: float = 0.0
        self._last_update: float = time.monotonic()

    def _drain(self, now: float) -> None:
        elapsed = now - self._last_update
        self._level = max(0.0, self._level - elapsed * self.leak_rate)
        self._last_update = now

    def request(self, amount: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            self._drain(now)
            if self._level + amount <= self.capacity:
                self._level += amount
                return True
            return False

    def reset(self) -> None:
        with self._lock:
            self._level = 0.0
            self._last_update = time.monotonic()

    def serialize(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            level = max(0.0, self._level - (now - self._last_update) * self.leak_rate)
            return {"level": level, "capacity": self.capacity, "full": level >= self.capacity}
