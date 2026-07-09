"""Datetime parsing/normalization helpers.

Storage convention: naive datetimes in UTC. All comparisons happen on
naive-UTC values; all responses carry an explicit UTC designator.
"""

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Aware current time in UTC."""
    return datetime.now(timezone.utc)


def now_utc_naive() -> datetime:
    """Naive current time in UTC (storage convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc(dt: datetime) -> datetime:
    """Normalize input to aware UTC. Naive input is treated as UTC;
    offset-carrying input is converted (not relabeled)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_naive_utc(dt: datetime) -> datetime:
    """Normalize input to naive UTC for storage/comparison."""
    return to_utc(dt).replace(tzinfo=None)


def isoformat_utc(dt: datetime) -> str:
    """ISO 8601 in UTC with explicit 'Z' designator."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")
