"""Internal tests for LeakyBucket."""

from __future__ import annotations

import pickle
import threading
import time
import unittest

from monsta import LeakyBucket


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

    def test_reset_empties_bucket(self):
        lb = LeakyBucket(capacity=2.0, leak_rate=0.001)
        lb.request(1.0)
        lb.request(1.0)
        self.assertFalse(lb.request(1.0))
        lb.reset()
        self.assertTrue(lb.request(1.0))

    def test_invalid_capacity(self):
        with self.assertRaises(ValueError):
            LeakyBucket(capacity=0, leak_rate=1.0)

    def test_invalid_leak_rate(self):
        with self.assertRaises(ValueError):
            LeakyBucket(capacity=10.0, leak_rate=0)

    def test_concurrent_requests(self):
        lb = LeakyBucket(capacity=1000.0, leak_rate=0.001)
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(1000):
                    lb.request(0.1)
                    lb.serialize()
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread errors: {errors}")

    def test_pickle_round_trip(self):
        lb = LeakyBucket(capacity=10.0, leak_rate=1.0)
        lb.request(3.0)
        lb2 = pickle.loads(pickle.dumps(lb))
        self.assertTrue(lb2.request(1.0))


if __name__ == "__main__":
    unittest.main()
