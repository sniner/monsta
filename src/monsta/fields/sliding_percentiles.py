from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Sequence
from typing import Any

from .base import Field


class SlidingPercentiles(Field):
    """Tracks quantiles over a sliding time window.

    Useful for latencies and other heavy-tailed signals where mean and
    standard deviation are misleading. Holds individual samples within
    the last ``window`` seconds (capped at ``max_samples``) and computes
    the requested quantiles on demand using linear interpolation
    (matching ``numpy.percentile`` with the default method).

    Older samples are dropped lazily on the next ``update`` or
    ``serialize`` call. When the cap is reached, the oldest sample is
    discarded so the most recent ``max_samples`` always win — that means
    under sustained high throughput the effective window may shrink
    below ``window`` seconds. Pick the cap accordingly.

    API:
        - ``update(sample)`` — record one observation
        - ``reset()``        — drop all samples

    Quantiles are floats in the closed interval ``[0, 100]``. The
    serialized output uses ``f"p{q:g}"`` as the key, so ``p50``,
    ``p99``, ``p99.9`` all work.

    Example::

        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.db_latency = SlidingPercentiles(
                    window=600.0,
                    quantiles=(50, 90, 95, 99),
                )

        state.db_latency.update(query_ms)
    """

    def __init__(
        self,
        window: float = 600.0,
        *,
        quantiles: Sequence[float] = (50, 90, 95, 99),
        max_samples: int = 10_000,
    ) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        if max_samples <= 0:
            raise ValueError(f"max_samples must be positive, got {max_samples}")
        qs = tuple(float(q) for q in quantiles)
        if not qs:
            raise ValueError("at least one quantile is required")
        for q in qs:
            if not (0.0 <= q <= 100.0):
                raise ValueError(f"quantile must be in [0, 100], got {q}")
        self.window = window
        self.quantiles = qs
        self.max_samples = max_samples
        self._lock = threading.Lock()
        self._samples: deque[tuple[float, float]] = deque(maxlen=max_samples)

    def _sweep(self, now: float) -> None:
        cutoff = now - self.window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def update(self, sample: float | int) -> None:
        with self._lock:
            now = time.monotonic()
            self._sweep(now)
            self._samples.append((now, float(sample)))

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()

    @staticmethod
    def _percentile(sorted_values: list[float], q: float) -> float:
        # Linear interpolation between the two nearest ranks (numpy
        # default, "type 7" in the Hyndman-Fan taxonomy).
        n = len(sorted_values)
        if n == 1:
            return sorted_values[0]
        rank = (q / 100.0) * (n - 1)
        lo = int(rank)
        hi = min(lo + 1, n - 1)
        frac = rank - lo
        return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac

    def serialize(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            self._sweep(now)
            if not self._samples:
                result: dict[str, Any] = {"n": 0}
                for q in self.quantiles:
                    result[f"p{q:g}"] = 0.0
                result["min"] = 0.0
                result["max"] = 0.0
                return result
            values = sorted(v for _, v in self._samples)
            result = {"n": len(values)}
            for q in self.quantiles:
                result[f"p{q:g}"] = self._percentile(values, q)
            result["min"] = values[0]
            result["max"] = values[-1]
            return result
