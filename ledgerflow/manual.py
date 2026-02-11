from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .hashing import canonical_json_bytes, sha256_bytes
from .ids import new_id
from .timeutil import parse_ymd, today_ymd, utc_now_iso


@dataclass(frozen=True)
class ManualEntry:
    occurred_at: str
    amount_value: Decimal
    currency: str
    merchant: str
    description: str | None = None
    category_hint: str | None = None
    tags: list[str] | None = None
    receipt_doc_id: str | None = None
    bill_doc_id: str | None = None


def parse_amount(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as e:
        raise ValueError(f"Invalid amount: {value}") from e


def manual_entry_to_tx(entry: ManualEntry) -> dict[str, Any]:
    occurred_at = parse_ymd(entry.occurred_at)
    posted_at = occurred_at
    created_at = utc_now_iso()

    amount_val = entry.amount_value
    direction = "debit" if amount_val < 0 else "credit"

    # Hash over the logical input to support later dedup/reconciliation.
    entry_hash_obj = {
        "occurredAt": occurred_at,
        "amount": {"value": str(amount_val), "currency": entry.currency},
        "merchant": entry.merchant,
        "description": entry.description or "",
        "categoryHint": entry.category_hint or "",
        "tags": entry.tags or [],
        "links": {"receiptDocId": entry.receipt_doc_id, "billDocId": entry.bill_doc_id},
    }
    source_hash = "sha256:" + sha256_bytes(canonical_json_bytes(entry_hash_obj))

    category_id = entry.category_hint or "uncategorized"
    cat_conf = 1.0 if entry.category_hint else 0.0
    cat_reason = "category_hint" if entry.category_hint else "missing"

    tx = {
        "txId": new_id("tx"),
        "source": {
            "docId": new_id("doc"),
            "sourceType": "manual",
            "sourceHash": source_hash,
            "lineRef": "manual:entry:1",
        },
        "postedAt": posted_at,
        "occurredAt": occurred_at,
        # Keep value as a decimal string to avoid float rounding errors.
        "amount": {"value": str(amount_val), "currency": entry.currency},
        "direction": direction,
        "merchant": entry.merchant,
        "description": entry.description or "",
        "category": {"id": category_id, "confidence": cat_conf, "reason": cat_reason},
        "tags": entry.tags or [],
        "confidence": {
            "extraction": 1.0,
            "normalization": 1.0,
            "categorization": cat_conf,
        },
        "links": {"receiptDocId": entry.receipt_doc_id, "billDocId": entry.bill_doc_id},
        "createdAt": created_at,
    }
    return tx


def correction_event(
    tx_id: str,
    *,
    patch: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "eventId": new_id("evt"),
        "txId": tx_id,
        "type": "patch",
        "patch": patch,
        "reason": reason,
        "at": utc_now_iso(),
    }


def tombstone_event(tx_id: str, *, reason: str) -> dict[str, Any]:
    return {
        "eventId": new_id("evt"),
        "txId": tx_id,
        "type": "tombstone",
        "reason": reason,
        "at": utc_now_iso(),
    }
