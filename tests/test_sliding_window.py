"""Internal tests for SlidingWindow."""

from __future__ import annotations

import pickle
import unittest
from unittest import mock

from monsta import SlidingWindow
from monsta.fields import sliding_window


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class TestSlidingWindow(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        patcher = mock.patch.object(sliding_window.time, "monotonic", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_init_zero(self):
        sw = SlidingWindow(window=10.0)
        self.assertEqual(sw.serialize(), 0.0)

    def test_inc_accumulates(self):
        sw = SlidingWindow(window=10.0)
        sw.inc()
        sw.inc()
        sw.inc(3.0)
        self.assertAlmostEqual(sw.serialize(), 5.0)

    def test_iadd_alias_for_inc(self):
        sw = SlidingWindow(window=10.0)
        sw += 1
        sw += 1
        sw += 1
        self.assertAlmostEqual(sw.serialize(), 3.0)

    def test_set_overwrites_current_bucket(self):
        sw = SlidingWindow(window=10.0, buckets=10)
        sw.inc(5)
        self.clock.now += 1.0
        sw.inc(5)
        sw.set(2)
        self.assertAlmostEqual(sw.serialize(), 7.0)

    def test_reset_clears_state(self):
        sw = SlidingWindow(window=10.0)
        sw.inc(5)
        self.clock.now += 3.0
        sw.inc(5)
        sw.reset()
        self.assertEqual(sw.serialize(), 0.0)

    def test_single_event_counts_for_the_whole_window(self):
        # Buckets are 60 s wide; the event lands 30 s into its bucket.
        self.clock.now = 30.0
        sw = SlidingWindow(window=3600.0, buckets=60)
        sw.inc()
        for t in (30.0, 600.0, 1800.0, 3599.0):
            self.clock.now = t
            self.assertAlmostEqual(sw.serialize(), 1.0, msg=f"t={t}")
        # The bucket leaves the window between t=3600 and t=3660.
        self.clock.now = 3630.0
        self.assertAlmostEqual(sw.serialize(), 0.5)
        self.clock.now = 3660.0
        self.assertEqual(sw.serialize(), 0.0)

    def test_steady_rate_gives_steady_value(self):
        sw = SlidingWindow(window=60.0, buckets=6)
        # One event per second for five minutes, read every second.
        values = []
        for _ in range(300):
            sw.inc()
            self.clock.now += 1.0
            values.append(sw.serialize())
        for v in values[70:]:
            self.assertAlmostEqual(v, 60.0)

    def test_one_bucket_fades_over_whole_window(self):
        self.clock.now = 30.0
        sw = SlidingWindow(window=60.0, buckets=1)
        sw.inc()
        self.clock.now = 59.0
        self.assertAlmostEqual(sw.serialize(), 1.0)
        self.clock.now = 90.0
        self.assertAlmostEqual(sw.serialize(), 0.5)
        self.clock.now = 120.0
        self.assertEqual(sw.serialize(), 0.0)

    def test_window_expiry_after_long_idle(self):
        sw = SlidingWindow(window=10.0, buckets=5)
        sw.inc(100)
        self.clock.now += 1000.0
        self.assertEqual(sw.serialize(), 0.0)
        sw.inc(1)
        self.assertAlmostEqual(sw.serialize(), 1.0)

    def test_invalid_window(self):
        with self.assertRaises(ValueError):
            SlidingWindow(window=0)
        with self.assertRaises(ValueError):
            SlidingWindow(window=-1)

    def test_invalid_buckets(self):
        with self.assertRaises(ValueError):
            SlidingWindow(window=10.0, buckets=0)

    def test_pickle_round_trip(self):
        sw = SlidingWindow(window=60.0)
        sw.inc(5)
        sw2 = pickle.loads(pickle.dumps(sw))
        self.assertAlmostEqual(sw2.serialize(), 5.0)
        sw2.inc(3)  # lock works after restore
        self.assertAlmostEqual(sw2.serialize(), 8.0)


if __name__ == "__main__":
    unittest.main()
