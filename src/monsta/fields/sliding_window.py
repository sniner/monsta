from __future__ import annotations

import threading
import time

from .base import Field


class SlidingWindow(Field):
    """Counter over the last ``window`` seconds, useful for rates.

    The window is divided into ``buckets`` buckets of ``window / buckets``
    seconds each. ``serialize()`` returns the sum of the buckets that cover
    the last ``window`` seconds. The oldest bucket is weighted by the part
    of it that is still inside the window, so a steady rate gives a steady
    value. A single event counts fully for at least ``window - window /
    buckets`` seconds and then drops to zero within one bucket.

    More buckets make the edges sharper at the cost of one float per
    bucket. ``buckets=1`` gives a coarse estimate: an event counts fully
    only until the next bucket boundary and then fades out over a whole
    ``window``.

    API:
        - ``inc(amount=1.0)`` — atomically add ``amount`` to the current bucket
        - ``state.x += n``    — alias for ``inc(n)``, also atomic
        - ``set(value)``      — overwrite the current bucket (e.g. external sync)
        - ``reset()``         — clear all buckets
    """

    def __init__(self, window: float = 60.0, *, buckets: int = 60) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        if buckets < 1:
            raise ValueError(f"buckets must be at least 1, got {buckets}")
        self.window = window
        self.buckets = buckets
        self._width = window / buckets
        self._lock = threading.Lock()
        # One bucket more than ``buckets``: the oldest one is partly outside
        # the window and still contributes with its remaining fraction.
        self._slots: list[float] = [0.0] * (buckets + 1)
        self._last_idx: int = int(time.monotonic() // self._width)

    def _sync(self, now: float) -> int:
        idx = int(now // self._width)
        elapsed = idx - self._last_idx
        if elapsed > 0:
            n = len(self._slots)
            for i in range(self._last_idx + 1, self._last_idx + 1 + min(elapsed, n)):
                self._slots[i % n] = 0.0
            self._last_idx = idx
        return idx

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            idx = self._sync(time.monotonic())
            self._slots[idx % len(self._slots)] += float(amount)

    def set(self, value: float) -> None:
        with self._lock:
            idx = self._sync(time.monotonic())
            self._slots[idx % len(self._slots)] = float(value)

    def reset(self) -> None:
        with self._lock:
            self._slots = [0.0] * (self.buckets + 1)
            self._last_idx = int(time.monotonic() // self._width)

    def __iadd__(self, amount: float) -> SlidingWindow:
        self.inc(amount)
        # Returning self is critical: AppState.__setattr__ then sees a
        # Field-to-Field rebind (same instance) and lets it through.
        return self

    def serialize(self) -> float:
        with self._lock:
            now = time.monotonic()
            idx = self._sync(now)
            # _sync has cleared everything older than ``buckets`` buckets, so
            # the ring holds exactly the current bucket and the ``buckets``
            # before it. The oldest of them sits at idx - buckets, which is
            # idx + 1 modulo the ring size.
            oldest = self._slots[(idx + 1) % len(self._slots)]
            elapsed = (now % self._width) / self._width
            return sum(self._slots) - oldest * elapsed
