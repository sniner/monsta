from __future__ import annotations

import threading
from typing import Any, Mapping

from .fields import ScalarField, StateField


class AppState:
    """Base class for structured monitoring state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _PLAIN_TYPES = (int, float, str, bool, type(None))
        for key, value in list(cls.__dict__.items()):
            if key.startswith("_"):
                continue
            if isinstance(value, (StateField, property)) or callable(value):
                continue
            if isinstance(value, _PLAIN_TYPES):
                field = ScalarField(default=value)
                field.__set_name__(cls, key)
                setattr(cls, key, field)

    def __enter__(self) -> AppState:
        self._lock.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self._lock.release()

    def __call__(self) -> Mapping[str, Any]:
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, Any] = {}

            mro_fields: dict[str, StateField] = {}
            for cls in reversed(type(self).__mro__):
                for attr_name, attr_val in cls.__dict__.items():
                    if isinstance(attr_val, StateField):
                        mro_fields[attr_name] = attr_val

            storage_keys: set[str] = set()
            for field_name, descriptor in mro_fields.items():
                storage_key = f"__field_{field_name}__"
                storage_keys.add(storage_key)
                result[field_name] = descriptor._get_impl(self).serialize()

            for key, value in self.__dict__.items():
                if key.startswith("_") or key in storage_keys:
                    continue
                if hasattr(value, "serialize") and callable(value.serialize):
                    result[key] = value.serialize()
                else:
                    result[key] = value

            return result
