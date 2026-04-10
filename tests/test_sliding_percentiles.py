"""Internal tests for SlidingPercentiles."""

from __future__ import annotations

import pickle
import time
import unittest

from monsta import SlidingPercentiles


class TestSlidingPercentiles(unittest.TestCase):
    def test_empty_state(self):
        sp = SlidingPercentiles(window=60.0)
        result = sp.serialize()
        self.assertEqual(result["n"], 0)
        for q in (50, 90, 95, 99):
            self.assertAlmostEqual(result[f"p{q}"], 0.0)
        self.assertAlmostEqual(result["min"], 0.0)
        self.assertAlmostEqual(result["max"], 0.0)

    def test_single_sample_all_quantiles_equal(self):
        sp = SlidingPercentiles(window=60.0)
        sp.update(42.0)
        result = sp.serialize()
        self.assertEqual(result["n"], 1)
        for q in (50, 90, 95, 99):
            self.assertAlmostEqual(result[f"p{q}"], 42.0)
        self.assertAlmostEqual(result["min"], 42.0)
        self.assertAlmostEqual(result["max"], 42.0)

    def test_known_quantiles(self):
        # Values 1..10 (sorted). Linear interpolation, n=10:
        #   rank(q) = q/100 * (n-1) = q/100 * 9
        #   p50 → rank 4.5 → (5+6)/2 = 5.5
        #   p90 → rank 8.1 → 9 + 0.1*(10-9) = 9.1
        sp = SlidingPercentiles(window=60.0, quantiles=(50, 90))
        for v in [3, 7, 1, 9, 5, 2, 8, 6, 4, 10]:  # unsorted on purpose
            sp.update(v)
        result = sp.serialize()
        self.assertEqual(result["n"], 10)
        self.assertAlmostEqual(result["p50"], 5.5)
        self.assertAlmostEqual(result["p90"], 9.1)
        self.assertAlmostEqual(result["min"], 1.0)
        self.assertAlmostEqual(result["max"], 10.0)

    def test_window_expiry_drops_old_samples(self):
        sp = SlidingPercentiles(window=0.05)
        sp.update(100)
        time.sleep(0.1)
        # Next update sweeps the old sample first.
        sp.update(5)
        result = sp.serialize()
        self.assertEqual(result["n"], 1)
        self.assertAlmostEqual(result["p50"], 5.0)

    def test_window_expiry_visible_via_serialize_only(self):
        # Even without further updates, serialize() should sweep on read.
        sp = SlidingPercentiles(window=0.05)
        sp.update(100)
        time.sleep(0.1)
        result = sp.serialize()
        self.assertEqual(result["n"], 0)

    def test_max_samples_cap(self):
        sp = SlidingPercentiles(window=60.0, max_samples=5)
        for v in [1, 2, 3, 4, 5, 6, 7]:
            sp.update(v)
        result = sp.serialize()
        # Only the last 5 samples (3..7) survive.
        self.assertEqual(result["n"], 5)
        self.assertAlmostEqual(result["min"], 3.0)
        self.assertAlmostEqual(result["max"], 7.0)

    def test_custom_quantiles(self):
        sp = SlidingPercentiles(window=60.0, quantiles=(25, 75))
        for v in range(1, 11):
            sp.update(v)
        result = sp.serialize()
        self.assertIn("p25", result)
        self.assertIn("p75", result)
        # rank(25) = 0.25*9 = 2.25 → values[2] + 0.25*(values[3]-values[2]) = 3 + 0.25 = 3.25
        self.assertAlmostEqual(result["p25"], 3.25)
        # rank(75) = 0.75*9 = 6.75 → values[6] + 0.75*(values[7]-values[6]) = 7 + 0.75 = 7.75
        self.assertAlmostEqual(result["p75"], 7.75)

    def test_fractional_quantile_key(self):
        sp = SlidingPercentiles(window=60.0, quantiles=(99.9,))
        sp.update(1.0)
        result = sp.serialize()
        # f"{99.9:g}" → "99.9"
        self.assertIn("p99.9", result)

    def test_reset_clears(self):
        sp = SlidingPercentiles(window=60.0)
        for v in range(1, 11):
            sp.update(v)
        sp.reset()
        result = sp.serialize()
        self.assertEqual(result["n"], 0)
        self.assertAlmostEqual(result["min"], 0.0)

    def test_invalid_window(self):
        with self.assertRaises(ValueError):
            SlidingPercentiles(window=0)
        with self.assertRaises(ValueError):
            SlidingPercentiles(window=-1)

    def test_invalid_max_samples(self):
        with self.assertRaises(ValueError):
            SlidingPercentiles(window=60.0, max_samples=0)
        with self.assertRaises(ValueError):
            SlidingPercentiles(window=60.0, max_samples=-1)

    def test_invalid_empty_quantiles(self):
        with self.assertRaises(ValueError):
            SlidingPercentiles(window=60.0, quantiles=())

    def test_invalid_quantile_out_of_range(self):
        with self.assertRaises(ValueError):
            SlidingPercentiles(window=60.0, quantiles=(50, 101))
        with self.assertRaises(ValueError):
            SlidingPercentiles(window=60.0, quantiles=(-1, 50))

    def test_p0_and_p100_match_extremes(self):
        sp = SlidingPercentiles(window=60.0, quantiles=(0, 100))
        for v in [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]:
            sp.update(v)
        result = sp.serialize()
        self.assertAlmostEqual(result["p0"], 1.0)
        self.assertAlmostEqual(result["p100"], 9.0)

    def test_pickle_round_trip(self):
        sp = SlidingPercentiles(window=60.0, quantiles=(50, 95))
        for v in range(1, 11):
            sp.update(v)
        sp2 = pickle.loads(pickle.dumps(sp))
        result = sp2.serialize()
        self.assertEqual(result["n"], 10)
        self.assertAlmostEqual(result["p50"], 5.5)
        # Lock works after restore.
        sp2.update(11)
        self.assertEqual(sp2.serialize()["n"], 11)


if __name__ == "__main__":
    unittest.main()
