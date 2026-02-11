from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from .money import decimal_from_any


def tx_date(tx: dict[str, Any]) -> str:
    d = tx.get("occurredAt") or tx.get("postedAt")
    return str(d) if d else ""


def tx_month(tx: dict[str, Any]) -> str:
    d = tx_date(tx)
    return d[:7] if len(d) >= 7 else ""


def tx_amount_decimal(tx: dict[str, Any]) -> Decimal:
    amt = tx.get("amount") or {}
    return decimal_from_any((amt.get("value") if isinstance(amt, dict) else None))


def tx_currency(tx: dict[str, Any]) -> str:
    amt = tx.get("amount") or {}
    if isinstance(amt, dict):
        return str(amt.get("currency") or "")
    return ""


def tx_category_id(tx: dict[str, Any]) -> str:
    cat = tx.get("category") or {}
    if isinstance(cat, dict):
        return str(cat.get("id") or "")
    return ""


def tx_category_confidence(tx: dict[str, Any]) -> float:
    cat = tx.get("category") or {}
    if not isinstance(cat, dict):
        return 0.0
    c = cat.get("confidence")
    try:
        return float(c) if c is not None else 0.0
    except Exception:
        return 0.0


def tx_merchant(tx: dict[str, Any]) -> str:
    m = str(tx.get("merchant") or "").strip()
    if m:
        return m
    # For bank CSV imports we often only have description.
    return str(tx.get("description") or "").strip()


def tx_source_type(tx: dict[str, Any]) -> str:
    src = tx.get("source") or {}
    if isinstance(src, dict):
        return str(src.get("sourceType") or "")
    return ""


def parse_ymd(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def daterange(from_date: str, to_date: str) -> list[str]:
    start = parse_ymd(from_date)
    end = parse_ymd(to_date)
    if end < start:
        raise ValueError("to_date must be >= from_date")
    out: list[str] = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out

