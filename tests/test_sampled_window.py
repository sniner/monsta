"""Internal tests for SampledWindow."""

from __future__ import annotations

import pickle
import time
import unittest

from monsta import SampledWindow


class TestSampledWindow(unittest.TestCase):
    def test_returns_zero_before_set(self):
        sw = SampledWindow(window=10.0, zero=0.0)
        self.assertAlmostEqual(sw.serialize(), 0.0)

    def test_returns_value_after_set(self):
        sw = SampledWindow(window=10.0, zero=0.0)
        sw.set(42.0)
        self.assertAlmostEqual(sw.serialize(), 42.0)

    def test_falls_back_to_zero_after_window(self):
        sw = SampledWindow(window=0.05, zero=0.0)
        sw.set(99.0)
        time.sleep(0.1)
        self.assertAlmostEqual(sw.serialize(), 0.0)

    def test_custom_zero_value(self):
        sw = SampledWindow(window=0.05, zero=-1.0)
        self.assertAlmostEqual(sw.serialize(), -1.0)
        sw.set(5.0)
        time.sleep(0.1)
        self.assertAlmostEqual(sw.serialize(), -1.0)

    def test_reset_drops_value(self):
        sw = SampledWindow(window=10.0)
        sw.set(99.0)
        sw.reset()
        self.assertAlmostEqual(sw.serialize(), 0.0)

    def test_invalid_window(self):
        with self.assertRaises(ValueError):
            SampledWindow(window=0)
        with self.assertRaises(ValueError):
            SampledWindow(window=-1)

    def test_pickle_round_trip(self):
        sw = SampledWindow(window=60.0)
        sw.set(42.0)
        sw2 = pickle.loads(pickle.dumps(sw))
        self.assertAlmostEqual(sw2.serialize(), 42.0)


if __name__ == "__main__":
    unittest.main()
