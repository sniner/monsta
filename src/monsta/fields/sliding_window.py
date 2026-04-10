from __future__ import annotations

import threading
import time

from .base import Field


class SlidingWindow(Field):
    """Counter that averages a sliding interval, useful for rates.

    Returns the number of hits accumulated over the last ``window``
    seconds, with smooth interpolation across bucket boundaries. The
    counter has two adjacent buckets internally; ``serialize()`` mixes
    them by the elapsed fraction of the current bucket.

    API:
        - ``inc(amount=1.0)`` — atomically add ``amount`` to the current bucket
        - ``state.x += n``    — alias for ``inc(n)``, also atomic
        - ``set(value)``      — overwrite the current bucket (e.g. external sync)
        - ``reset()``         — clear both buckets
    """

    def __init__(self, window: float = 60.0) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        self.window = window
        self._lock = threading.Lock()
        self._prev: float = 0.0
        self._curr: float = 0.0
        self._last_idx: int = int(time.monotonic() // window)

    def _sync(self, now: float) -> None:
        idx = int(now // self.window)
        if idx > self._last_idx:
            self._prev = self._curr if idx == self._last_idx + 1 else 0.0
            self._curr = 0.0
            self._last_idx = idx

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._sync(time.monotonic())
            self._curr += float(amount)

    def set(self, value: float) -> None:
        with self._lock:
            self._sync(time.monotonic())
            self._curr = float(value)

    def reset(self) -> None:
        with self._lock:
            self._prev = 0.0
            self._curr = 0.0
            self._last_idx = int(time.monotonic() // self.window)

    def __iadd__(self, amount: float) -> SlidingWindow:
        self.inc(amount)
        # Returning self is critical: AppState.__setattr__ then sees a
        # Field-to-Field rebind (same instance) and lets it through.
        return self

    def serialize(self) -> float:
        with self._lock:
            now = time.monotonic()
            self._sync(now)
            weight = max(0.0, min(1.0, (self.window - now % self.window) / self.window))
            return (self._prev * weight) + self._curr
