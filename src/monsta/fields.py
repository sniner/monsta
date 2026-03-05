from __future__ import annotations

import math
import threading
import time
from abc import ABC, abstractmethod
from typing import Any


class FieldImpl(ABC):
    @abstractmethod
    def update(self, value: Any) -> None: ...

    @abstractmethod
    def serialize(self) -> Any: ...


class StateField:
    _name: str
    _storage_key: str

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name
        self._storage_key = f"__field_{name}__"

    def _make_impl(self) -> FieldImpl:
        raise NotImplementedError

    def _get_impl(self, obj: Any) -> FieldImpl:
        if not hasattr(self, "_storage_key"):
            raise RuntimeError("StateField must be declared as a class attribute")
        impl = obj.__dict__.get(self._storage_key)
        if impl is None:
            impl = obj.__dict__.setdefault(self._storage_key, self._make_impl())
        return impl

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return self._get_impl(obj).serialize()

    def __set__(self, obj: Any, value: Any) -> None:
        self._get_impl(obj).update(value)


class ScalarImpl(FieldImpl):
    def __init__(self, default: Any) -> None:
        self._value = default
        self.lock = threading.Lock()

    def update(self, value: Any) -> None:
        with self.lock:
            self._value = value

    def serialize(self) -> Any:
        with self.lock:
            return self._value


class ScalarField(StateField):
    def __init__(self, default: Any = None) -> None:
        self._default = default

    def _make_impl(self) -> ScalarImpl:
        return ScalarImpl(self._default)


class SlidingWindowImpl(FieldImpl):
    def __init__(self, window: float) -> None:
        self.window = window
        self.lock = threading.Lock()
        self.prev: float = 0.0
        self.curr: float = 0.0
        self.last_idx: int = int(time.monotonic() // window)

    def _sync(self, now: float) -> None:
        idx = int(now // self.window)
        if idx > self.last_idx:
            self.prev = self.curr if idx == self.last_idx + 1 else 0.0
            self.curr = 0.0
            self.last_idx = idx

    def update(self, value: float | int) -> None:
        with self.lock:
            now = time.monotonic()
            self._sync(now)
            self.curr += float(value)

    def serialize(self) -> float:
        with self.lock:
            now = time.monotonic()
            self._sync(now)
            weight = max(0.0, min(1.0, (self.window - now % self.window) / self.window))
            return (self.prev * weight) + self.curr


class SlidingWindow(StateField):
    def __init__(self, window: float = 60.0) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        self._window = window

    def _make_impl(self) -> SlidingWindowImpl:
        return SlidingWindowImpl(self._window)


class EWMAImpl(FieldImpl):
    def __init__(self, alpha: float, *, preset: float | None = None) -> None:
        self.alpha = alpha
        self.value: float | None = preset
        self.lock = threading.Lock()

    def update(self, value: float | int) -> None:
        with self.lock:
            v = float(value)
            self.value = (
                v if self.value is None else self.alpha * v + (1.0 - self.alpha) * self.value
            )

    def serialize(self) -> float | None:
        with self.lock:
            return self.value


class EWMA(StateField):
    def __init__(self, alpha: float = 0.1, *, preset: float | None = None) -> None:
        if not (0.0 < alpha <= 1.0):
            raise ValueError(f"alpha must be in (0.0, 1.0], got {alpha}")
        self._alpha = alpha
        self._preset = preset

    def _make_impl(self) -> EWMAImpl:
        return EWMAImpl(self._alpha, preset=self._preset)


class RunningStatsImpl(FieldImpl):
    def __init__(self) -> None:
        self.n: int = 0
        self.mean: float = 0.0
        self.m2: float = 0.0
        self.min: float | None = None
        self.max: float | None = None
        self.lock = threading.Lock()

    def update(self, value: float | int) -> None:
        with self.lock:
            x = float(value)
            self.n += 1
            delta = x - self.mean
            self.mean += delta / self.n
            self.m2 += delta * (x - self.mean)
            self.min = x if self.min is None else min(self.min, x)
            self.max = x if self.max is None else max(self.max, x)

    def serialize(self) -> dict[str, Any]:
        with self.lock:
            variance = self.m2 / self.n if self.n > 1 else 0.0
            return {
                "n": self.n,
                "mean": self.mean,
                "stddev": math.sqrt(variance),
                "min": 0.0 if self.min is None else self.min,
                "max": 0.0 if self.max is None else self.max,
            }


class RunningStats(StateField):
    def _make_impl(self) -> RunningStatsImpl:
        return RunningStatsImpl()


class SampledWindowImpl(FieldImpl):
    def __init__(self, window: float, *, zero: float = 0.0) -> None:
        self.window = window
        self.zero = zero
        self._value: float = zero
        self._last_update: float = 0.0
        self.lock = threading.Lock()

    def update(self, value: float | int) -> None:
        with self.lock:
            self._value = float(value)
            self._last_update = time.monotonic()

    def serialize(self) -> float:
        with self.lock:
            if time.monotonic() - self._last_update <= self.window:
                return self._value
            return self.zero


class SampledWindow(StateField):
    """Hold the last assigned value for a window duration, then fall back to zero.

    Unlike SlidingWindow (which accumulates), SampledWindow simply holds the
    most recently assigned value until the window expires.
    """

    def __init__(self, window: float = 60.0, zero: float = 0.0) -> None:
        if window <= 0:
            raise ValueError(f"window must be positive, got {window}")
        self._window = window
        self._zero = zero

    def _make_impl(self) -> SampledWindowImpl:
        return SampledWindowImpl(self._window, zero=self._zero)


class LeakyBucketImpl(FieldImpl):

    def __init__(self, capacity: float, leak_rate: float) -> None:
        self.capacity = capacity
        self.leak_rate = leak_rate
        self._level: float = 0.0
        self._last_update: float = time.monotonic()
        self._lock = threading.Lock()

    def update(self, value: Any) -> None:
        raise AttributeError(
            "LeakyBucket does not support assignment. Use .request() to consume tokens."
        )

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

    def serialize(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            level = max(0.0, self._level - (now - self._last_update) * self.leak_rate)
            return {"level": level, "capacity": self.capacity, "full": level >= self.capacity}


class LeakyBucket(StateField):
    """Token bucket rate limiter field.

    Declare as a class attribute on AppState. Access via the attribute returns
    the impl object so you can call .request() on it directly.

    Example:
        class MyState(AppState):
            rate_limit = LeakyBucket(capacity=10, leak_rate=1)

        # Usage:
        if state.rate_limit.request():
            ...  # proceed
    """

    def __init__(self, capacity: float, leak_rate: float) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        if leak_rate <= 0:
            raise ValueError(f"leak_rate must be positive, got {leak_rate}")
        self._capacity = capacity
        self._leak_rate = leak_rate

    def _make_impl(self) -> LeakyBucketImpl:
        return LeakyBucketImpl(self._capacity, self._leak_rate)

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return self._get_impl(obj)

    def __set__(self, obj: Any, value: Any) -> None:
        raise AttributeError(
            "LeakyBucket does not support assignment. Use .request() to consume tokens."
        )
