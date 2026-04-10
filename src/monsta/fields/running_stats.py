from __future__ import annotations

import math
import threading
from typing import Any

from .base import Field


class RunningStats(Field):
    """Tracks mean, standard deviation, min and max over all samples seen.

    Constant memory regardless of sample count (Welford's algorithm).
    ``min`` and ``max`` are reported as ``0.0`` before the first sample,
    matching the historical behaviour.

    API:
        - ``update(sample)`` — add one observation
        - ``reset()``        — clear all accumulated stats
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._n: int = 0
        self._mean: float = 0.0
        self._m2: float = 0.0
        self._min: float | None = None
        self._max: float | None = None

    def update(self, sample: float | int) -> None:
        with self._lock:
            x = float(sample)
            self._n += 1
            delta = x - self._mean
            self._mean += delta / self._n
            self._m2 += delta * (x - self._mean)
            self._min = x if self._min is None else min(self._min, x)
            self._max = x if self._max is None else max(self._max, x)

    def reset(self) -> None:
        with self._lock:
            self._n = 0
            self._mean = 0.0
            self._m2 = 0.0
            self._min = None
            self._max = None

    def serialize(self) -> dict[str, Any]:
        with self._lock:
            variance = self._m2 / self._n if self._n > 1 else 0.0
            return {
                "n": self._n,
                "mean": self._mean,
                "stddev": math.sqrt(variance),
                "min": 0.0 if self._min is None else self._min,
                "max": 0.0 if self._max is None else self._max,
            }
