"""
Unit tests for AppState, SlidingWindow, EWMA, RunningStats, and LeakyBucket.
"""

from __future__ import annotations

import json
import math
import threading
import time
import unittest

from monsta import AppState, EWMA, LeakyBucket, RunningStats, SlidingWindow
from monsta.fields import (
    EWMAImpl,
    LeakyBucket,
    RunningStatsImpl,
    SlidingWindowImpl,
)


class TestSlidingWindow(unittest.TestCase):
    def _make_impl(self, window: float = 10.0) -> SlidingWindowImpl:
        return SlidingWindowImpl(window)

    def test_init_zero(self):
        impl = self._make_impl()
        self.assertEqual(impl.serialize(), 0.0)

    def test_hit_accumulates(self):
        impl = self._make_impl(window=10.0)
        impl.update(1)
        impl.update(1)
        impl.update(1)
        rate = impl.serialize()
        self.assertGreater(rate, 0.0)

    def test_amount_greater_than_one(self):
        impl = self._make_impl(window=10.0)
        impl.update(5)
        rate = impl.serialize()
        self.assertGreater(rate, 0.0)

    def test_window_expiry(self):
        """After more than two window-lengths the rate should be 0."""
        window = 0.05
        impl = SlidingWindowImpl(window)
        impl.update(100)
        time.sleep(window * 2.5)
        self.assertEqual(impl.serialize(), 0.0)

    def test_invalid_window(self):
        with self.assertRaises(ValueError):
            SlidingWindow(window=0)
        with self.assertRaises(ValueError):
            SlidingWindow(window=-1)

    def test_descriptor_as_class_attr(self):
        class S(AppState):
            rate = SlidingWindow(window=60.0)

        s = S()
        self.assertEqual(s.rate, 0.0)
        s.rate = 3
        self.assertGreater(s.rate, 0.0)


class TestEWMA(unittest.TestCase):
    def _make_impl(self, alpha: float = 0.5) -> EWMAImpl:
        return EWMAImpl(alpha)

    def test_first_value(self):
        impl = self._make_impl(alpha=0.5)
        impl.update(10.0)
        self.assertAlmostEqual(impl.serialize(), 10.0)

    def test_smoothing_formula(self):
        impl = self._make_impl(alpha=0.5)
        impl.update(10.0)
        impl.update(0.0)
        # 0.5 * 0.0 + 0.5 * 10.0 = 5.0
        self.assertAlmostEqual(impl.serialize(), 5.0)

    def test_uninitialized_is_none(self):
        impl = self._make_impl()
        self.assertIsNone(impl.serialize())

    def test_invalid_alpha_zero(self):
        with self.assertRaises(ValueError):
            EWMA(alpha=0.0)

    def test_invalid_alpha_greater_one(self):
        with self.assertRaises(ValueError):
            EWMA(alpha=1.1)

    def test_alpha_one_replaces(self):
        impl = self._make_impl(alpha=1.0)
        impl.update(42.0)
        impl.update(7.0)
        self.assertAlmostEqual(impl.serialize(), 7.0)


class TestRunningStats(unittest.TestCase):
    def _make_impl(self) -> RunningStatsImpl:
        return RunningStatsImpl()

    def test_empty_state(self):
        impl = self._make_impl()
        result = impl.serialize()
        self.assertEqual(result["n"], 0)
        self.assertAlmostEqual(result["mean"], 0.0)
        self.assertAlmostEqual(result["stddev"], 0.0)
        self.assertIsNone(result["min"])
        self.assertIsNone(result["max"])

    def test_single_value(self):
        impl = self._make_impl()
        impl.update(42.0)
        result = impl.serialize()
        self.assertEqual(result["n"], 1)
        self.assertAlmostEqual(result["mean"], 42.0)
        self.assertAlmostEqual(result["stddev"], 0.0)
        self.assertAlmostEqual(result["min"], 42.0)
        self.assertAlmostEqual(result["max"], 42.0)

    def test_known_variance(self):
        # Dataset: 2, 4, 4, 4, 5, 5, 7, 9  → mean=5.0, variance=4.0, stddev=2.0
        impl = self._make_impl()
        for v in [2, 4, 4, 4, 5, 5, 7, 9]:
            impl.update(v)
        result = impl.serialize()
        self.assertEqual(result["n"], 8)
        self.assertAlmostEqual(result["mean"], 5.0)
        self.assertAlmostEqual(result["stddev"], 2.0, places=10)
        self.assertAlmostEqual(result["min"], 2.0)
        self.assertAlmostEqual(result["max"], 9.0)

    def test_serialize_keys(self):
        impl = self._make_impl()
        impl.update(1)
        result = impl.serialize()
        self.assertIn("n", result)
        self.assertIn("mean", result)
        self.assertIn("stddev", result)
        self.assertIn("min", result)
        self.assertIn("max", result)


class TestLeakyBucket(unittest.TestCase):
    def test_allow_within_capacity(self):
        lb = LeakyBucket(capacity=5.0, leak_rate=1.0)
        for _ in range(5):
            self.assertTrue(lb.request(1.0))

    def test_reject_when_full(self):
        lb = LeakyBucket(capacity=2.0, leak_rate=0.001)
        lb.request(1.0)
        lb.request(1.0)
        self.assertFalse(lb.request(1.0))

    def test_leak_allows_retry(self):
        lb = LeakyBucket(capacity=1.0, leak_rate=10.0)
        lb.request(1.0)
        time.sleep(0.2)
        self.assertTrue(lb.request(1.0))

    def test_serialize_structure(self):
        lb = LeakyBucket(capacity=100.0, leak_rate=10.0)
        s = lb.serialize()
        self.assertIn("level", s)
        self.assertIn("capacity", s)
        self.assertIn("full", s)
        self.assertEqual(s["capacity"], 100.0)
        self.assertFalse(s["full"])

    def test_serialize_non_mutating(self):
        lb = LeakyBucket(capacity=1.0, leak_rate=0.001)
        lb.request(1.0)
        s1 = lb.serialize()
        s2 = lb.serialize()
        self.assertAlmostEqual(s1["level"], s2["level"], places=2)

    def test_invalid_capacity(self):
        with self.assertRaises(ValueError):
            LeakyBucket(capacity=0, leak_rate=1.0)

    def test_invalid_leak_rate(self):
        with self.assertRaises(ValueError):
            LeakyBucket(capacity=10.0, leak_rate=0)


class TestAppState(unittest.TestCase):
    def test_declaration(self):
        class S(AppState):
            rate = SlidingWindow(window=60.0)
            cpu = EWMA(alpha=0.1)
            latency = RunningStats()

        s = S()
        d = s.to_dict()
        self.assertIn("rate", d)
        self.assertIn("cpu", d)
        self.assertIn("latency", d)

    def test_field_assignment(self):
        class S(AppState):
            cpu = EWMA(alpha=1.0)

        s = S()
        s.cpu = 55.0
        self.assertAlmostEqual(s.cpu, 55.0)

    def test_plain_attr(self):
        class S(AppState):
            pass

        s = S()
        s.status = "running"
        d = s.to_dict()
        self.assertEqual(d["status"], "running")

    def test_leaky_bucket_as_instance_attr(self):
        class S(AppState):
            pass

        s = S()
        s.limiter = LeakyBucket(capacity=100, leak_rate=10)
        d = s.to_dict()
        self.assertIn("limiter", d)
        self.assertIn("level", d["limiter"])
        self.assertIn("capacity", d["limiter"])

    def test_callable_interface(self):
        class S(AppState):
            hits = SlidingWindow(window=60.0)

        s = S()
        result = s()
        self.assertIsInstance(result, dict)
        self.assertIn("hits", result)

    def test_inheritance(self):
        class Base(AppState):
            base_metric = EWMA(alpha=0.5)

        class Child(Base):
            child_metric = RunningStats()

        c = Child()
        d = c.to_dict()
        self.assertIn("base_metric", d)
        self.assertIn("child_metric", d)

    def test_child_overrides_parent(self):
        class Base(AppState):
            metric = EWMA(alpha=0.5)

        class Child(Base):
            metric = RunningStats()

        c = Child()
        c.metric = 42
        d = c.to_dict()
        # Child's RunningStats should win, so n==1
        self.assertEqual(d["metric"]["n"], 1)

    def test_independent_instances(self):
        class S(AppState):
            cpu = EWMA(alpha=1.0)

        s1 = S()
        s2 = S()
        s1.cpu = 10.0
        s2.cpu = 90.0
        self.assertAlmostEqual(s1.cpu, 10.0)
        self.assertAlmostEqual(s2.cpu, 90.0)

    def test_json_serializable(self):
        class S(AppState):
            rate = SlidingWindow(window=60.0)
            cpu = EWMA(alpha=0.1)
            latency = RunningStats()

        s = S()
        s.rate = 1
        s.cpu = 50.0
        s.latency = 100
        s.status = "ok"
        # Should not raise
        json.dumps(s.to_dict())

    def test_no_field_storage_keys_in_output(self):
        class S(AppState):
            rate = SlidingWindow(window=60.0)

        s = S()
        s.rate = 5
        d = s.to_dict()
        for key in d:
            self.assertFalse(key.startswith("__field_"), f"Found internal key {key!r} in output")

    def test_ewma_none_before_update(self):
        class S(AppState):
            cpu = EWMA(alpha=0.1)

        s = S()
        d = s.to_dict()
        self.assertIsNone(d["cpu"])

    def test_running_stats_empty(self):
        class S(AppState):
            latency = RunningStats()

        s = S()
        d = s.to_dict()
        self.assertEqual(d["latency"]["n"], 0)


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_updates(self):
        class S(AppState):
            hits = SlidingWindow(window=60.0)
            cpu = EWMA(alpha=0.1)
            latency = RunningStats()

        s = S()
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(1000):
                    s.hits = 1
                    s.cpu = 50.0
                    s.latency = 42
                    s.to_dict()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread errors: {errors}")

    def test_concurrent_leaky_bucket(self):
        lb = LeakyBucket(capacity=1000.0, leak_rate=0.001)
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(1000):
                    lb.request(0.1)
                    lb.serialize()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread errors: {errors}")


if __name__ == "__main__":
    unittest.main()
