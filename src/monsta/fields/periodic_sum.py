from __future__ import annotations

import datetime
import threading

from .base import Field


class PeriodicSum(Field):
    """Accumulating counter that snaps to zero at a fixed wall-clock time.

    Useful for "events today", "requests since midnight", and similar
    calendar-aligned counters. Reset happens lazily: the next read or
    write after the configured time triggers the rollover.

    API:
        - ``inc(amount=1.0)`` — atomically add ``amount``
        - ``state.x += n``    — alias for ``inc(n)``, also atomic
        - ``set(value)``      — overwrite (e.g. sync to an external counter)
        - ``reset()``         — set to zero immediately

    ``reset_at`` is a ``datetime.time`` interpreted in ``tz`` (or local
    naive time if ``tz`` is None). Reset times that fall inside a DST gap
    or repeated hour may shift slightly on transition days; the default
    midnight reset is unaffected.

    Example::

        from datetime import time
        from zoneinfo import ZoneInfo

        class S(AppState):
            def __init__(self):
                super().__init__()
                self.jobs_today = PeriodicSum()
                self.requests_today = PeriodicSum(
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
        self.reset_at = reset_at
        self.tz = tz
        self._lock = threading.Lock()
        self._value: float = 0.0
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

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._sync(self._now())
            self._value += float(amount)

    def set(self, value: float) -> None:
        with self._lock:
            self._sync(self._now())
            self._value = float(value)

    def reset(self) -> None:
        with self._lock:
            self._value = 0.0
            self._period_start = self._period_start_for(self._now())

    def __iadd__(self, amount: float) -> PeriodicSum:
        self.inc(amount)
        return self

    def serialize(self) -> float:
        with self._lock:
            self._sync(self._now())
            return self._value
