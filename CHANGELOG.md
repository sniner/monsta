# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com).

## [0.2.0] — 2026-04-10

The metric-field model has been redesigned. Fields are now plain instance
objects declared in `__init__` instead of class-level descriptors. Counter
increments via `+=` are genuinely atomic, and each field exposes explicit
methods (`inc`, `set`, `update`, `request`, `reset`) instead of overloading
assignment.

### Breaking changes

- **`AppState` field declaration** — fields must be assigned in `__init__`.
  The old `class MyState(AppState): hits = SlidingWindow(...)` form raises
  `TypeError` at class definition time, with a message pointing at this
  changelog. Wrap declarations in `def __init__(self): super().__init__();
  self.hits = SlidingWindow(...)`.
- **Field assignment semantics** — direct assignment to a Field attribute
  is rejected by an `AppState` setattr guard. Use the explicit methods
  instead: counters → `state.hits.inc()` or `state.hits += 1`; samplers
  → `state.cpu.update(73.5)`; holders → `state.active_rps.set(120)`;
  rate limiter → `state.lim.request()` (unchanged).
- **`state.cpu` returns a Field, not a value** — accessing a field
  attribute now returns the `Field` instance itself. To read the current
  value, call `state.cpu.serialize()` or read `state.to_dict()["cpu"]`.
- **`ScalarField` removed** — declare plain instance attributes in
  `__init__` instead (`self.api_calls: int = 0`). They are still picked up
  by `to_dict()` automatically.
- **`StateField` / `*Impl` classes removed** — the field/impl split is
  gone. Subclass `Field` directly if you need a custom field type.

#### Migration guide

Before (0.1.x):

```python
class MyState(AppState):
    hits        = SlidingWindow(window=60)
    cpu         = EWMA(alpha=0.1)
    api_calls: int = 0

state.hits = 1            # was "increment"
state.cpu  = 73.5         # was "feed sample"
state.api_calls += 1
```

After (0.2.0):

```python
class MyState(AppState):
    def __init__(self) -> None:
        super().__init__()
        self.hits = SlidingWindow(window=60)
        self.cpu  = EWMA(alpha=0.1)
        self.api_calls: int = 0

state.hits += 1           # atomic increment
state.cpu.update(73.5)    # explicit observation
state.api_calls += 1
```

### Added

- **`SlidingPercentiles`** — new sampler field that tracks configurable
  quantiles over a sliding time window. Designed for latencies and other
  heavy-tailed signals where mean/stddev are misleading. Holds individual
  samples (capped via `max_samples`, default 10 000) and computes quantiles
  on demand via linear interpolation. Defaults to `window=600` seconds and
  `quantiles=(50, 90, 95, 99)`. Empty state reports zeros instead of nulls
  so dashboards do not need null-handling.
- **Atomic counter increments** — `SlidingWindow` and `PeriodicSum` now
  expose `inc(amount=1.0)` and an `__iadd__` that delegates to it. Both
  forms are atomic across threads. The 0.1.x threading caveat is gone.
- **`Field` base class** — exported from the package for custom field
  subclasses and `isinstance` checks.
- **`reset()` on every field** — explicit method to return any field to
  its initial state without re-instantiating it.
- **Setattr guard on `AppState`** — replacing a `Field` attribute with a
  non-`Field` value raises `TypeError` with a hint pointing at the right
  method. Field-to-Field replacement (subclass overrides) is still
  allowed.
- **Migration guard** — class-scope field declarations raise a clear
  `TypeError` at class definition time, with a pointer to this changelog.
- **Pickle support** — all fields drop their lock on pickling and
  re-create it on unpickling, so `pickle.dumps(state)` round-trips.
- **Tests split** — internal field tests live in `tests/test_fields.py`,
  user-facing API tests in `tests/test_appstate.py`.

### Removed

- **`ScalarField`**, **`StateField`**, **`FieldImpl`**, and all `*Impl`
  classes (`SlidingWindowImpl`, `EWMAImpl`, `RunningStatsImpl`,
  `SampledWindowImpl`, `PeriodicSumImpl`, `LeakyBucketImpl`).
- **Auto-conversion of class-level annotations** to `ScalarField` via
  `__init_subclass__`. Plain instance attributes in `__init__` cover the
  same use case more transparently.
