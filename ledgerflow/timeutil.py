from __future__ import annotations

from datetime import date, datetime, timezone


def utc_now_iso() -> str:
    # ISO8601 with second precision, Z suffix.
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_ymd() -> str:
    return date.today().isoformat()


def parse_ymd(value: str) -> str:
    # Validate YYYY-MM-DD.
    datetime.strptime(value, "%Y-%m-%d")
    return value

