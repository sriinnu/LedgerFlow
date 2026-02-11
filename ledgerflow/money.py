from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def decimal_from_any(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # Convert through str to preserve what was stored.
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return Decimal("0")
        try:
            return Decimal(s)
        except InvalidOperation as e:
            raise ValueError(f"Invalid decimal: {value!r}") from e
    raise TypeError(f"Unsupported decimal type: {type(value).__name__}")


def fmt_decimal(d: Decimal) -> str:
    # Keep as non-scientific where possible.
    return format(d, "f")

