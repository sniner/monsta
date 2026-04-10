"""Internal tests for PeriodicSum."""

from __future__ import annotations

import datetime
import pickle
import unittest
from zoneinfo import ZoneInfo

from monsta import PeriodicSum


class TestPeriodicSum(unittest.TestCase):
    def test_init_zero(self):
        ps = PeriodicSum()
        self.assertEqual(ps.serialize(), 0.0)

    def test_inc_accumulates(self):
        ps = PeriodicSum()
        ps.inc()
        ps.inc(2.5)
        ps.inc()
        self.assertAlmostEqual(ps.serialize(), 4.5)

    def test_iadd_alias_for_inc(self):
        ps = PeriodicSum()
        ps += 1
        ps += 1
        ps += 1
        self.assertAlmostEqual(ps.serialize(), 3.0)

    def test_set_overwrites(self):
        ps = PeriodicSum()
        ps.inc(7)
        ps.set(2)
        self.assertAlmostEqual(ps.serialize(), 2.0)

    def test_reset_clears(self):
        ps = PeriodicSum()
        ps.inc(7)
        ps.reset()
        self.assertAlmostEqual(ps.serialize(), 0.0)

    def test_resets_after_period(self):
        ps = PeriodicSum()
        ps.inc(10)
        self.assertAlmostEqual(ps.serialize(), 10.0)
        # Pretend the current period started two days ago.
        ps._period_start -= datetime.timedelta(days=2)
        self.assertAlmostEqual(ps.serialize(), 0.0)
        ps.inc(4)
        self.assertAlmostEqual(ps.serialize(), 4.0)

    def test_period_start_for_midnight(self):
        ps = PeriodicSum(reset_at=datetime.time(0, 0))
        now = datetime.datetime(2026, 4, 10, 15, 30, 0)
        self.assertEqual(
            ps._period_start_for(now), datetime.datetime(2026, 4, 10, 0, 0, 0)
        )

    def test_period_start_for_custom_time_before(self):
        ps = PeriodicSum(reset_at=datetime.time(6, 0))
        # 05:00 is before today's 06:00 reset → still in yesterday's period.
        now = datetime.datetime(2026, 4, 10, 5, 0, 0)
        self.assertEqual(
            ps._period_start_for(now), datetime.datetime(2026, 4, 9, 6, 0, 0)
        )

    def test_period_start_for_custom_time_after(self):
        ps = PeriodicSum(reset_at=datetime.time(6, 0))
        now = datetime.datetime(2026, 4, 10, 7, 0, 0)
        self.assertEqual(
            ps._period_start_for(now), datetime.datetime(2026, 4, 10, 6, 0, 0)
        )

    def test_with_tz(self):
        tz = ZoneInfo("Europe/Berlin")
        ps = PeriodicSum(tz=tz)
        self.assertIsNotNone(ps._period_start.tzinfo)
        self.assertEqual(ps._period_start.tzinfo, tz)
        ps.inc(2)
        self.assertAlmostEqual(ps.serialize(), 2.0)

    def test_invalid_reset_at(self):
        with self.assertRaises(TypeError):
            PeriodicSum(reset_at="00:00")  # type: ignore[arg-type]

    def test_pickle_round_trip(self):
        ps = PeriodicSum()
        ps.inc(7)
        ps2 = pickle.loads(pickle.dumps(ps))
        self.assertAlmostEqual(ps2.serialize(), 7.0)
        ps2.inc(3)
        self.assertAlmostEqual(ps2.serialize(), 10.0)


if __name__ == "__main__":
    unittest.main()
