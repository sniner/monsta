from __future__ import annotations

import threading

from .base import Field


class EWMA(Field):
    """Exponentially-weighted moving average.

    ``alpha`` ∈ ``(0, 1]`` controls smoothing — values near ``0`` are
    very smooth, ``1`` means no smoothing (returns the latest sample).
    Returns ``None`` until the first sample arrives, unless ``preset``
    seeds an initial value.

    API:
        - ``update(sample)`` — feed one observation
        - ``reset()``        — drop accumulated state, return to ``preset``/None
    """

    def __init__(self, alpha: float = 0.1, *, preset: float | None = None) -> None:
        if not (0.0 < alpha <= 1.0):
            raise ValueError(f"alpha must be in (0.0, 1.0], got {alpha}")
        self.alpha = alpha
        self._preset = preset
        self._value: float | None = preset
        self._lock = threading.Lock()

    def update(self, sample: float | int) -> None:
        with self._lock:
            v = float(sample)
            self._value = (
                v if self._value is None else self.alpha * v + (1.0 - self.alpha) * self._value
            )

    def reset(self) -> None:
        with self._lock:
            self._value = self._preset

    def serialize(self) -> float | None:
        with self._lock:
            return self._value
