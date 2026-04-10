"""
User-facing API tests for AppState.

These tests exercise only the public API: AppState subclassing, field
declaration in __init__, to_dict(), the context manager, the setattr
guard, the migration guard, and the integration contracts (callable,
JSON-serializable, +=  atomicity). A diff in this file means the
user-visible API has changed — review carefully.
"""

from __future__ import annotations

import json
import threading
import unittest

from monsta import (
    EWMA,
    AppState,
    LeakyBucket,
    PeriodicSum,
    RunningStats,
    SampledWindow,
    SlidingPercentiles,
    SlidingWindow,
)


class TestAppStateBasics(unittest.TestCase):
    def test_field_declaration_in_init(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.rate = SlidingWindow(window=60.0)
                self.cpu = EWMA(alpha=0.1)
                self.latency = RunningStats()

        s = S()
        d = s.to_dict()
        self.assertIn("rate", d)
        self.assertIn("cpu", d)
        self.assertIn("latency", d)

    def test_to_dict_preserves_init_order(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.first = SlidingWindow(window=60.0)
                self.second = EWMA(alpha=0.1)
                self.third = RunningStats()

        s = S()
        self.assertEqual(list(s.to_dict().keys()), ["first", "second", "third"])

    def test_independent_instances(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.cpu = EWMA(alpha=1.0)

        s1, s2 = S(), S()
        s1.cpu.update(10.0)
        s2.cpu.update(90.0)
        self.assertAlmostEqual(s1.cpu.serialize(), 10.0)
        self.assertAlmostEqual(s2.cpu.serialize(), 90.0)

    def test_no_internal_keys_in_output(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.rate = SlidingWindow(window=60.0)

        s = S()
        s.rate.inc(5)
        for key in s.to_dict():
            self.assertFalse(key.startswith("_"), f"leaked internal key {key!r}")

    def test_ewma_none_before_update(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.cpu = EWMA(alpha=0.1)

        s = S()
        self.assertIsNone(s.to_dict()["cpu"])

    def test_running_stats_empty(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.latency = RunningStats()

        s = S()
        self.assertEqual(s.to_dict()["latency"]["n"], 0)


class TestPlainInstanceAttrs(unittest.TestCase):
    def test_plain_attr_in_to_dict(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.api_calls: int = 0
                self.name: str = "default"
                self.ratio: float = 1.5
                self.active: bool = True

        s = S()
        d = s.to_dict()
        self.assertEqual(d["api_calls"], 0)
        self.assertEqual(d["name"], "default")
        self.assertAlmostEqual(d["ratio"], 1.5)
        self.assertEqual(d["active"], True)

    def test_plain_attr_iadd(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.count: int = 0

        s = S()
        s.count += 1
        s.count += 2
        self.assertEqual(s.count, 3)
        self.assertEqual(s.to_dict()["count"], 3)

    def test_plain_attr_assignment(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.status: str = "starting"

        s = S()
        s.status = "running"
        self.assertEqual(s.to_dict()["status"], "running")


class TestSetattrGuard(unittest.TestCase):
    def test_assigning_non_field_to_field_raises(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.hits = SlidingWindow(window=60.0)

        s = S()
        with self.assertRaises(TypeError) as ctx:
            s.hits = 0
        msg = str(ctx.exception)
        self.assertIn("hits", msg)
        self.assertIn("set", msg)

    def test_field_to_field_replacement_allowed(self):
        # Subclass override path: child __init__ may rebind the parent
        # field with a different Field type.
        class Parent(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.metric = EWMA(alpha=0.1)

        class Child(Parent):
            def __init__(self) -> None:
                super().__init__()
                self.metric = RunningStats()

        c = Child()
        self.assertIsInstance(c.metric, RunningStats)

    def test_iadd_does_not_trigger_guard(self):
        # __iadd__ rebinds the same instance back, which is Field-to-Field
        # and must NOT raise.
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.hits = SlidingWindow(window=60.0)

        s = S()
        s.hits += 1
        s.hits += 1
        s.hits += 1
        self.assertAlmostEqual(s.hits.serialize(), 3.0)

    def test_periodicsum_iadd_does_not_trigger_guard(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.jobs = PeriodicSum()

        s = S()
        s.jobs += 5
        self.assertAlmostEqual(s.jobs.serialize(), 5.0)

    def test_leaky_bucket_assignment_raises(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.lim = LeakyBucket(capacity=10.0, leak_rate=1.0)

        s = S()
        with self.assertRaises(TypeError):
            s.lim = "oops"


class TestMigrationGuard(unittest.TestCase):
    def test_class_scope_field_raises_at_class_definition(self):
        with self.assertRaises(TypeError) as ctx:

            class Bad(AppState):  # noqa: F841 — exercising __init_subclass__
                hits = SlidingWindow(window=60.0)

        msg = str(ctx.exception)
        self.assertIn("hits", msg)
        self.assertIn("__init__", msg)
        self.assertIn("CHANGELOG", msg)

    def test_class_scope_other_field_types(self):
        for field_factory in (
            lambda: EWMA(alpha=0.1),
            lambda: RunningStats(),
            lambda: SampledWindow(window=10.0),
            lambda: PeriodicSum(),
            lambda: LeakyBucket(capacity=10.0, leak_rate=1.0),
        ):
            with self.assertRaises(TypeError):

                class Bad(AppState):  # noqa: F841
                    metric = field_factory()


class TestContextManager(unittest.TestCase):
    def test_context_manager_returns_self(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.val: int = 0

        s = S()
        with s as ctx:
            self.assertIs(ctx, s)

    def test_reentrant_to_dict_in_context(self):
        # RLock allows the same thread to call to_dict() while holding
        # the lock via `with state:`.
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.val: int = 0

        s = S()
        with s:
            s.val = 7
            d = s.to_dict()
        self.assertEqual(d["val"], 7)

    def test_other_thread_blocked_during_context(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.val: int = 0

        s = S()
        reader_done = threading.Event()
        reader_observed: list[int] = []

        def reader():
            d = s.to_dict()
            reader_observed.append(d["val"])
            reader_done.set()

        with s:
            s.val = 7
            t = threading.Thread(target=reader)
            t.start()
            # Reader is blocked on the RLock; give it a brief moment.
            self.assertFalse(reader_done.wait(timeout=0.1))
        t.join(timeout=1.0)
        self.assertTrue(reader_done.is_set())
        self.assertEqual(reader_observed, [7])


class TestIaddAtomicity(unittest.TestCase):
    """Regression sentinel for the entire 0.2.0 redesign.

    If this fails, atomicity is broken — fix it before shipping.
    """

    def test_sliding_window_iadd_atomic(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.hits = SlidingWindow(window=60.0)

        s = S()

        def worker():
            for _ in range(1000):
                s.hits += 1

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 10 threads × 1000 increments must be exactly 10000.
        self.assertAlmostEqual(s.hits._curr, 10000.0)

    def test_periodic_sum_iadd_atomic(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.jobs = PeriodicSum()

        s = S()

        def worker():
            for _ in range(1000):
                s.jobs += 1

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertAlmostEqual(s.jobs.serialize(), 10000.0)

    def test_inc_method_atomic(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.hits = SlidingWindow(window=60.0)

        s = S()

        def worker():
            for _ in range(1000):
                s.hits.inc()

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertAlmostEqual(s.hits._curr, 10000.0)


class TestThreadSafetyToDict(unittest.TestCase):
    def test_concurrent_updates_and_reads(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.hits = SlidingWindow(window=60.0)
                self.cpu = EWMA(alpha=0.1)
                self.latency = RunningStats()

        s = S()
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(500):
                    s.hits += 1
                    s.cpu.update(50.0)
                    s.latency.update(42)
                    s.to_dict()
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread errors: {errors}")
        # All 8 × 500 increments must show up.
        self.assertAlmostEqual(s.hits._curr, 4000.0)


class TestInheritance(unittest.TestCase):
    def test_child_inherits_parent_fields(self):
        class Parent(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.base_metric = EWMA(alpha=0.5)

        class Child(Parent):
            def __init__(self) -> None:
                super().__init__()
                self.child_metric = RunningStats()

        c = Child()
        d = c.to_dict()
        self.assertIn("base_metric", d)
        self.assertIn("child_metric", d)

    def test_child_overrides_parent_field_with_different_type(self):
        class Parent(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.metric = EWMA(alpha=0.5)

        class Child(Parent):
            def __init__(self) -> None:
                super().__init__()
                self.metric = RunningStats()

        c = Child()
        c.metric.update(42)
        d = c.to_dict()
        self.assertEqual(d["metric"]["n"], 1)


class TestCallableProtocol(unittest.TestCase):
    def test_state_callable_returns_dict(self):
        # mon.publish(state) relies on AppState being callable so it can
        # treat it as a state-source callback.
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.hits = SlidingWindow(window=60.0)

        s = S()
        result = s()
        self.assertIsInstance(result, dict)
        self.assertIn("hits", result)

    def test_state_call_equivalent_to_to_dict(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.hits = SlidingWindow(window=60.0)
                self.status = "ok"

        s = S()
        s.hits.inc(3)
        self.assertEqual(s(), s.to_dict())


class TestJsonSerializable(unittest.TestCase):
    def test_all_field_types_round_trip(self):
        class S(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.hits = SlidingWindow(window=60.0)
                self.jobs = PeriodicSum()
                self.cpu = EWMA(alpha=0.1, preset=0.0)
                self.latency = RunningStats()
                self.db_latency = SlidingPercentiles(window=60.0)
                self.rps = SampledWindow(window=5.0)
                self.lim = LeakyBucket(capacity=10.0, leak_rate=1.0)
                self.count: int = 0
                self.status: str = "ok"

        s = S()
        s.hits += 1
        s.jobs += 1
        s.cpu.update(50.0)
        s.latency.update(42)
        s.db_latency.update(12.5)
        s.rps.set(120)
        s.lim.request()
        s.count += 1
        # Should not raise
        encoded = json.dumps(s.to_dict())
        decoded = json.loads(encoded)
        self.assertIn("hits", decoded)
        self.assertIn("level", decoded["lim"])
        self.assertIn("p95", decoded["db_latency"])


if __name__ == "__main__":
    unittest.main()
