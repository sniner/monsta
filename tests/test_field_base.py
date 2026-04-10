"""
Tests for the Field abstract base class defaults.

These exercise the default behaviour every Field subclass inherits if it
doesn't override the relevant method: raising reset(), raising __iadd__,
and a __repr__ that does NOT call serialize() (so future O(N) fields
stay cheap to print at debug time).
"""

from __future__ import annotations

import unittest

from monsta import (
    EWMA,
    Field,
    LeakyBucket,
    RunningStats,
    SampledWindow,
    SlidingPercentiles,
    SlidingWindow,
)


class TestFieldBaseDefaults(unittest.TestCase):
    """Defaults defined on the Field base class."""

    def test_reset_raises_by_default(self):
        # A custom Field subclass that doesn't override reset() should
        # inherit the raising default.
        class Custom(Field):
            def serialize(self):
                return None

        with self.assertRaises(NotImplementedError):
            Custom().reset()

    def test_iadd_raises_by_default(self):
        class Custom(Field):
            def serialize(self):
                return None

        c = Custom()
        with self.assertRaises(TypeError) as ctx:
            c += 1  # noqa: F841 — exercising the operator
        self.assertIn("Custom", str(ctx.exception))

    def test_repr_does_not_call_serialize(self):
        # Critical for forward-compat with O(N) fields (median, percentile)
        # whose serialize() could be expensive.
        calls = []

        class Custom(Field):
            def serialize(self):
                calls.append(1)
                return "expensive"

        r = repr(Custom())
        self.assertIn("Custom", r)
        self.assertEqual(calls, [], "repr() must not call serialize()")

    def test_repr_default_includes_typename(self):
        self.assertIn("SlidingWindow", repr(SlidingWindow(window=60.0)))
        self.assertIn("EWMA", repr(EWMA(alpha=0.1)))

    def test_iadd_rejected_on_non_counter_fields(self):
        # Sampler/holder fields inherit the raising default.
        for f in (
            EWMA(alpha=0.1),
            RunningStats(),
            SampledWindow(window=10.0),
            LeakyBucket(capacity=10.0, leak_rate=1.0),
            SlidingPercentiles(window=60.0),
        ):
            with self.assertRaises(TypeError):
                f += 1  # noqa: F841


if __name__ == "__main__":
    unittest.main()
