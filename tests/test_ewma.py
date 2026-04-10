"""Internal tests for EWMA."""

from __future__ import annotations

import pickle
import unittest

from monsta import EWMA


class TestEWMA(unittest.TestCase):
    def test_uninitialized_is_none(self):
        e = EWMA(alpha=0.5)
        self.assertIsNone(e.serialize())

    def test_first_value(self):
        e = EWMA(alpha=0.5)
        e.update(10.0)
        self.assertAlmostEqual(e.serialize(), 10.0)

    def test_smoothing_formula(self):
        e = EWMA(alpha=0.5)
        e.update(10.0)
        e.update(0.0)
        # 0.5 * 0.0 + 0.5 * 10.0 = 5.0
        self.assertAlmostEqual(e.serialize(), 5.0)

    def test_alpha_one_replaces(self):
        e = EWMA(alpha=1.0)
        e.update(42.0)
        e.update(7.0)
        self.assertAlmostEqual(e.serialize(), 7.0)

    def test_invalid_alpha_zero(self):
        with self.assertRaises(ValueError):
            EWMA(alpha=0.0)

    def test_invalid_alpha_greater_one(self):
        with self.assertRaises(ValueError):
            EWMA(alpha=1.1)

    def test_preset_returned_before_update(self):
        e = EWMA(alpha=0.5, preset=5.0)
        self.assertAlmostEqual(e.serialize(), 5.0)

    def test_preset_used_in_formula(self):
        e = EWMA(alpha=0.5, preset=10.0)
        e.update(0.0)
        # 0.5 * 0.0 + 0.5 * 10.0 = 5.0
        self.assertAlmostEqual(e.serialize(), 5.0)

    def test_reset_returns_to_preset(self):
        e = EWMA(alpha=0.5, preset=5.0)
        e.update(99.0)
        e.reset()
        self.assertAlmostEqual(e.serialize(), 5.0)

    def test_reset_returns_to_none(self):
        e = EWMA(alpha=0.5)
        e.update(99.0)
        e.reset()
        self.assertIsNone(e.serialize())

    def test_pickle_round_trip(self):
        e = EWMA(alpha=0.5)
        e.update(10.0)
        e2 = pickle.loads(pickle.dumps(e))
        self.assertAlmostEqual(e2.serialize(), 10.0)
        e2.update(0.0)
        self.assertAlmostEqual(e2.serialize(), 5.0)


if __name__ == "__main__":
    unittest.main()
