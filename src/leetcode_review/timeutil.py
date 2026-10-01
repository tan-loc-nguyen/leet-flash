"""Small UTC time helpers. All persisted timestamps are ISO-8601 UTC strings ending in 'Z'."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def day_start(dt: datetime) -> datetime:
    """Midnight UTC of the day containing ``dt``."""
    return dt.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def from_epoch(value: str | int | float) -> str:
    return iso(datetime.fromtimestamp(float(value), UTC))
