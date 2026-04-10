"""Internal tests for SlidingWindow."""

from __future__ import annotations

import pickle
import time
import unittest

from monsta import SlidingWindow


class TestSlidingWindow(unittest.TestCase):
    def test_init_zero(self):
        sw = SlidingWindow(window=10.0)
        self.assertEqual(sw.serialize(), 0.0)

    def test_inc_accumulates(self):
        sw = SlidingWindow(window=10.0)
        sw.inc()
        sw.inc()
        sw.inc(3.0)
        self.assertGreater(sw.serialize(), 0.0)
        # Internally curr should be 5
        self.assertAlmostEqual(sw._curr, 5.0)

    def test_iadd_alias_for_inc(self):
        sw = SlidingWindow(window=10.0)
        sw += 1
        sw += 1
        sw += 1
        self.assertAlmostEqual(sw._curr, 3.0)

    def test_set_overwrites_current_bucket(self):
        sw = SlidingWindow(window=10.0)
        sw.inc(5)
        sw.set(2)
        self.assertAlmostEqual(sw._curr, 2.0)

    def test_reset_clears_state(self):
        sw = SlidingWindow(window=10.0)
        sw.inc(5)
        sw.reset()
        self.assertAlmostEqual(sw._curr, 0.0)
        self.assertAlmostEqual(sw._prev, 0.0)
        self.assertEqual(sw.serialize(), 0.0)

    def test_window_expiry(self):
        window = 0.05
        sw = SlidingWindow(window=window)
        sw.inc(100)
        time.sleep(window * 2.5)
        self.assertEqual(sw.serialize(), 0.0)

    def test_invalid_window(self):
        with self.assertRaises(ValueError):
            SlidingWindow(window=0)
        with self.assertRaises(ValueError):
            SlidingWindow(window=-1)

    def test_pickle_round_trip(self):
        sw = SlidingWindow(window=60.0)
        sw.inc(5)
        sw2 = pickle.loads(pickle.dumps(sw))
        self.assertAlmostEqual(sw2._curr, 5.0)
        sw2.inc(3)  # lock works after restore
        self.assertAlmostEqual(sw2._curr, 8.0)


if __name__ == "__main__":
    unittest.main()
