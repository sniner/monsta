from __future__ import annotations

import threading
from typing import Any

from .fields import Field


class AppState:
    """Base class for structured monitoring state.

    Declare fields as instance attributes inside ``__init__``::

        class MyState(AppState):
            def __init__(self) -> None:
                super().__init__()
                self.hits = SlidingWindow(window=60)
                self.cpu  = EWMA(alpha=0.1)
                self.api_calls: int = 0       # plain attr is fine
                self.status: str = "starting"

    Field objects expose explicit methods (``inc``, ``set``, ``update``,
    ``request``, ``reset``); ``state.hits += 1`` is shorthand for
    ``state.hits.inc(1)`` on counter-style fields and is genuinely atomic.

    Plain instance attributes are passed through to ``to_dict()`` as-is, so
    keep them JSON-serializable (or prefix internal helpers with ``_``).

    Use ``with state:`` to perform multi-field updates atomically::

        with state:
            state.api_calls += 1
            state.status = "degraded"
            state.cpu.update(95.0)

    Notes:
        - Subclasses must NOT use ``__slots__`` — ``to_dict()`` walks
          ``vars(self)``.
        - The lock is an ``RLock`` so ``with state:`` blocks may call
          ``state.to_dict()`` reentrantly without deadlock.
        - Lock invariant: the AppState RLock is always acquired BEFORE
          any individual field lock. Field locks are leaf locks; never
          acquire the AppState lock while holding a field lock.
        - Inheritance: child ``__init__`` may rebind a parent field
          (``self.metric = OtherField()``); the setattr guard allows
          Field-to-Field replacement. Be aware that any data the parent
          wrote to the original field is lost when you replace it.
    """

    # Class-level annotation so type checkers see _lock even though it
    # is bootstrapped via object.__setattr__ to bypass our own guard.
    _lock: threading.RLock

    def __init__(self) -> None:
        # Bypass our own __setattr__ guard while bootstrapping the lock.
        object.__setattr__(self, "_lock", threading.RLock())

    def __setattr__(self, name: str, value: Any) -> None:
        # Footgun guard: refuse to silently overwrite a Field with a
        # non-Field value. Allowed:
        #   - first-time assignment (current is None)
        #   - plain-attr reassignment (current is not a Field)
        #   - Field-to-Field replacement (subclass overrides + __iadd__
        #     rebinding the same instance back to itself).
        current = self.__dict__.get(name)
        if isinstance(current, Field) and not isinstance(value, Field):
            raise TypeError(
                f"Cannot replace Field {name!r} with {type(value).__name__}. "
                f"Use {name}.set(...), {name}.update(...), {name}.reset(), "
                f"or {name} += ... instead."
            )
        object.__setattr__(self, name, value)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Migration aid: detect 0.1.x-style class-level field declarations
        # and fail loudly with a clear message at class definition time.
        for key, val in cls.__dict__.items():
            if key.startswith("_"):
                continue
            if isinstance(val, Field):
                raise TypeError(
                    f"{cls.__name__}.{key} is a Field declared at class scope. "
                    f"Since monsta 0.2.0 fields must be assigned in __init__: "
                    f"`self.{key} = {type(val).__name__}(...)`. "
                    f"See CHANGELOG.md for the migration guide."
                )

    def __enter__(self) -> AppState:
        self._lock.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self._lock.release()

    def __call__(self) -> dict[str, Any]:
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = {}
            # vars(self) preserves insertion order (CPython 3.7+),
            # so output reflects __init__ declaration order.
            for name, value in vars(self).items():
                if name.startswith("_"):
                    continue
                if isinstance(value, Field):
                    result[name] = value.serialize()
                else:
                    result[name] = value
            return result
