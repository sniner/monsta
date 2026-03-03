from __future__ import annotations
from typing import Any, Mapping
from .fields import StateField


class AppState:
    """Base class for structured monitoring state."""

    def __call__(self) -> Mapping[str, Any]:
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}

        # Collect StateField descriptors from the entire MRO;
        # reversed() ensures child fields shadow parent fields of the same name.
        mro_fields: dict[str, StateField] = {}
        for cls in reversed(type(self).__mro__):
            for attr_name, attr_val in cls.__dict__.items():
                if isinstance(attr_val, StateField):
                    mro_fields[attr_name] = attr_val

        # Track storage keys so they are excluded when iterating instance __dict__.
        storage_keys: set[str] = set()
        for field_name, descriptor in mro_fields.items():
            storage_key = f'__field_{field_name}__'
            storage_keys.add(storage_key)
            result[field_name] = descriptor._get_impl(self).serialize()  # Lazy init

        # Serialize regular instance attributes.
        for key, value in self.__dict__.items():
            if key in storage_keys:
                continue
            if hasattr(value, 'serialize') and callable(value.serialize):
                result[key] = value.serialize()   # e.g. LeakyBucket
            else:
                result[key] = value

        return result
