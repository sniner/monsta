from __future__ import annotations

import datetime
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
            self.curr = float(value)

    def serialize(self) -> float:
        with self.lock:
            now = time.monotonic()
            self._sync(now)
            weight = max(0.0, min(1.0, (self.window - now % self.window) / self.window))
            return (self.prev * weight) + self.curr


class SlidingWindow(StateField):
    """Counter that averages a sliding interval, useful for rates.

    Use ``+=`` to record events; plain assignment overwrites the current
    bucket (useful for resetting to zero).

    Example:
        class S(AppState):
            request_rate = SlidingWindow(window=60.0)

        state.request_rate += 1   # one more hit
        state.request_rate = 0    # reset current bucket

    Threading note: ``+=`` is *not* atomic across threads. Python's
    descriptor protocol expands ``state.x += 1`` into a get/add/set
    sequence and the field's lock can only protect each step
    individually, so concurrent writers may lose updates. For
    single-writer scenarios this is fine; for multi-writer counters,
    serialize the increment yourself.
    """

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


class PeriodicSumImpl(FieldImpl):
    def __init__(self, reset_at: datetime.time, tz: datetime.tzinfo | None) -> None:
        self.reset_at = reset_at
        self.tz = tz
        self._value: float = 0.0
        self.lock = threading.Lock()
        self._period_start: datetime.datetime = self._period_start_for(self._now())

    def _now(self) -> datetime.datetime:
        return datetime.datetime.now(self.tz)

    def _period_start_for(self, now: datetime.datetime) -> datetime.datetime:
        today_reset = now.replace(
            hour=self.reset_at.hour,
            minute=self.reset_at.minute,
            second=self.reset_at.second,
            microsecond=self.reset_at.microsecond,
        )
        if now < today_reset:
            return today_reset - datetime.timedelta(days=1)
        return today_reset

    def _sync(self, now: datetime.datetime) -> None:
        start = self._period_start_for(now)
        if start > self._period_start:
            self._value = 0.0
            self._period_start = start

    def update(self, value: float | int) -> None:
        with self.lock:
            self._sync(self._now())
            self._value = float(value)

    def serialize(self) -> float:
        with self.lock:
            self._sync(self._now())
            return self._value


class PeriodicSum(StateField):
    """Accumulating counter that resets at a fixed wall-clock time each day.

    Unlike SlidingWindow (which averages a sliding interval), PeriodicSum
    accumulates values until a configurable time of day (default midnight)
    and then snaps back to zero. Useful for "events today", "requests since
    midnight" and similar calendar-aligned counters.

    Use ``+=`` to record events; plain assignment overwrites the current
    counter (useful for resetting to zero or syncing to an external value):

        state.jobs_today += 1   # adds 1 to today's total
        state.jobs_today = 0    # explicit reset

    Threading note: ``+=`` is *not* atomic across threads (see
    SlidingWindow for the underlying reason). Use single-writer or
    serialize increments yourself when multiple threads write.

    Note: ``reset_at`` is interpreted in the configured timezone (or local
    naive time if ``tz`` is None). Reset times that fall inside a DST gap
    or repeated hour may shift slightly on transition days; for the typical
    midnight default this is a non-issue.

    Example:
        from datetime import time
        from zoneinfo import ZoneInfo

        class S(AppState):
            jobs_today = PeriodicSum()  # reset at local midnight
            requests_today = PeriodicSum(
                reset_at=time(6, 0),
                tz=ZoneInfo("Europe/Berlin"),
            )
    """

    def __init__(
        self,
        reset_at: datetime.time = datetime.time(0, 0),
        tz: datetime.tzinfo | None = None,
    ) -> None:
        if not isinstance(reset_at, datetime.time):
            raise TypeError(
                f"reset_at must be a datetime.time, got {type(reset_at).__name__}"
            )
        self._reset_at = reset_at
        self._tz = tz

    def _make_impl(self) -> PeriodicSumImpl:
        return PeriodicSumImpl(self._reset_at, self._tz)


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
