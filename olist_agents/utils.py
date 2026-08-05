from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, TypeVar

T = TypeVar("T")
TWOPLACES = Decimal("0.01")


def stable_unique(values: Iterable[T]) -> list[T]:
    seen: set[T] = set()
    result: list[T] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def money(value: Decimal) -> float:
    rounded = value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return 0.0 if rounded == 0 else float(rounded)


def parse_decimal(value: str | None) -> Decimal:
    return Decimal(value) if value not in (None, "") else Decimal("0")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def variance_hours(later: str | None, earlier: str | None) -> float | None:
    left = parse_timestamp(later)
    right = parse_timestamp(earlier)
    if left is None or right is None:
        return None
    hours = Decimal(str((left - right).total_seconds())) / Decimal("3600")
    return money(hours)
