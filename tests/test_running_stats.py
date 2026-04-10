"""Internal tests for RunningStats."""

from __future__ import annotations

import pickle
import unittest

from monsta import RunningStats


class TestRunningStats(unittest.TestCase):
    def test_empty_state(self):
        r = RunningStats()
        result = r.serialize()
        self.assertEqual(result["n"], 0)
        self.assertAlmostEqual(result["mean"], 0.0)
        self.assertAlmostEqual(result["stddev"], 0.0)
        self.assertAlmostEqual(result["min"], 0.0)
        self.assertAlmostEqual(result["max"], 0.0)

    def test_single_value(self):
        r = RunningStats()
        r.update(42.0)
        result = r.serialize()
        self.assertEqual(result["n"], 1)
        self.assertAlmostEqual(result["mean"], 42.0)
        self.assertAlmostEqual(result["stddev"], 0.0)
        self.assertAlmostEqual(result["min"], 42.0)
        self.assertAlmostEqual(result["max"], 42.0)

    def test_known_variance(self):
        # 2,4,4,4,5,5,7,9 → mean 5.0, stddev 2.0
        r = RunningStats()
        for v in [2, 4, 4, 4, 5, 5, 7, 9]:
            r.update(v)
        result = r.serialize()
        self.assertEqual(result["n"], 8)
        self.assertAlmostEqual(result["mean"], 5.0)
        self.assertAlmostEqual(result["stddev"], 2.0, places=10)
        self.assertAlmostEqual(result["min"], 2.0)
        self.assertAlmostEqual(result["max"], 9.0)

    def test_serialize_keys(self):
        r = RunningStats()
        r.update(1)
        result = r.serialize()
        for k in ("n", "mean", "stddev", "min", "max"):
            self.assertIn(k, result)

    def test_min_max_zero_before_update(self):
        r = RunningStats()
        result = r.serialize()
        self.assertAlmostEqual(result["min"], 0.0)
        self.assertAlmostEqual(result["max"], 0.0)

    def test_min_max_correct_after_update(self):
        r = RunningStats()
        r.update(3.0)
        r.update(7.0)
        result = r.serialize()
        self.assertAlmostEqual(result["min"], 3.0)
        self.assertAlmostEqual(result["max"], 7.0)

    def test_reset_clears(self):
        r = RunningStats()
        r.update(3.0)
        r.update(7.0)
        r.reset()
        result = r.serialize()
        self.assertEqual(result["n"], 0)
        self.assertAlmostEqual(result["min"], 0.0)
        self.assertAlmostEqual(result["max"], 0.0)

    def test_pickle_round_trip(self):
        r = RunningStats()
        for v in [1, 2, 3, 4, 5]:
            r.update(v)
        r2 = pickle.loads(pickle.dumps(r))
        self.assertEqual(r2.serialize()["n"], 5)
        self.assertAlmostEqual(r2.serialize()["mean"], 3.0)


if __name__ == "__main__":
    unittest.main()
