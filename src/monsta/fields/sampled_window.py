from __future__ import annotations

import threading
import time

from .base import Field


class SampledWindow(Field):
    """Hold the last assigned value for ``window`` seconds, then return ``zero``.

    Unlike ``SlidingWindow`` (which accumulates), ``SampledWindow`` simply
    holds the most recent value until the window expires. Useful for rates
    or signals that should decay to zero when no fresh sample arrives.

    API:
        - ``set(value)`` — store value with current timestamp
        - ``reset()``    — drop the held value, fall back to ``zero``
    """

    def __init__(self, window: float = 60.0, zero: float = 0.0) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        self.window = window
        self.zero = zero
        self._lock = threading.Lock()
        self._value: float = zero
        self._last_update: float = 0.0

    def set(self, value: float | int) -> None:
        with self._lock:
            self._value = float(value)
            self._last_update = time.monotonic()

    def reset(self) -> None:
        with self._lock:
            self._value = self.zero
            self._last_update = 0.0

    def serialize(self) -> float:
        with self._lock:
            if time.monotonic() - self._last_update <= self.window:
                return self._value
            return self.zero
