from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any


class Field(ABC):
    """Base class for all metric fields.

    Fields are normal instance objects: declare them in your ``AppState``
    subclass's ``__init__`` and call methods on them directly. Each field
    owns its own lock — there is no shared field/impl split anymore.

    Subclasses must implement :meth:`serialize`. Methods like ``inc``,
    ``set``, ``update``, ``request`` and ``reset`` are field-specific and
    only exist where they are meaningful. The defaults on this base raise
    a clear error so misuse is caught loudly.

    ``__iadd__`` is the only operator the base provides, and it raises by
    default. Counter fields opt in by overriding it; sampler/holder fields
    inherit the default and reject ``state.x += y`` to keep semantics
    unambiguous.
    """

    @abstractmethod
    def serialize(self) -> Any:
        """Return the current value in JSON-compatible form."""

    def reset(self) -> None:
        """Reset to the field's initial state.

        Subclasses override where this makes sense. The default raises so
        callers find out at the call site if a field has no notion of
        reset.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support reset()"
        )

    def __iadd__(self, other: Any) -> Field:
        """Default ``+=`` rejects with a clear message.

        Counter-style fields (``SlidingWindow``, ``PeriodicSum``) override
        this with an atomic ``inc(other)``. Other fields keep this default
        so ``state.cpu += 1`` doesn't silently do something nonsensical.
        """
        raise TypeError(
            f"{type(self).__name__} does not support '+='. "
            f"Use the field's explicit method (.update / .set / .request) instead."
        )

    def __repr__(self) -> str:
        # Intentionally does NOT call serialize() — future O(N) fields
        # (median, percentiles) might produce huge reprs at debug time.
        # Subclasses can override for richer output if cheap.
        return f"<{type(self).__name__}>"

    def __getstate__(self) -> dict[str, Any]:
        # Drop the lock so pickling works. All concrete fields store
        # their lock under ``_lock``.
        state = dict(vars(self))
        state.pop("_lock", None)
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        # object.__setattr__ avoids any subclass __setattr__ side effects
        # and keeps pyright happy (self.__dict__ is typed as a read-only
        # MappingProxyType from the class side).
        for key, value in state.items():
            object.__setattr__(self, key, value)
        # The lock was stripped by __getstate__; re-create it.
        object.__setattr__(self, "_lock", threading.Lock())
