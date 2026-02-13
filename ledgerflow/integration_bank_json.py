from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .hashing import canonical_json_bytes, sha256_bytes
from .ids import new_id
from .index_db import has_source_hash
from .layout import Layout
from .sources import register_file
from .storage import append_jsonl
from .timeutil import parse_ymd, utc_now_iso


def _pick_text(row: dict[str, Any], keys: list[str], default: str = "") -> str:
    for key in keys:
        if key in row and row.get(key) is not None:
            v = str(row.get(key)).strip()
            if v:
                return v
    return default


def _parse_amount_value(value: Any) -> Decimal:
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as e:
        raise ValueError(f"invalid amount value: {value!r}") from e


def _parse_records(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict) and isinstance(raw.get("transactions"), list):
        rows = raw.get("transactions")
    else:
        raise ValueError("bank json must be a list or an object with 'transactions' list")
    out = [x for x in rows if isinstance(x, dict)]
    if not out:
        raise ValueError("bank json has no transaction objects")
    return out


def _row_to_tx(*, doc_id: str, row_index: int, row: dict[str, Any], default_currency: str) -> dict[str, Any]:
    occurred_at = _pick_text(row, ["occurredAt", "postedAt", "date", "bookingDate", "valueDate"])
    if not occurred_at:
        raise ValueError("missing date field (occurredAt|postedAt|date|bookingDate|valueDate)")
    parse_ymd(occurred_at)

    amount_obj = row.get("amount")
    if isinstance(amount_obj, dict):
        amount_value = _parse_amount_value(amount_obj.get("value"))
        currency = str(amount_obj.get("currency") or default_currency)
    else:
        amount_value = _parse_amount_value(row.get("amountValue", row.get("amount")))
        currency = _pick_text(row, ["currency", "ccy"], default=default_currency)

    merchant = _pick_text(row, ["merchant", "payee", "counterparty", "name"])
    description = _pick_text(row, ["description", "memo", "details", "narration"]) or merchant
    category_id = _pick_text(row, ["category", "categoryId"], default="uncategorized")
    direction = "debit" if amount_value < 0 else "credit"

    row_hash_obj = {
        "docId": doc_id,
        "rowIndex": row_index,
        "row": row,
    }
    source_hash = "sha256:" + sha256_bytes(canonical_json_bytes(row_hash_obj))

    return {
        "txId": new_id("tx"),
        "source": {
            "docId": doc_id,
            "sourceType": "bank_json",
            "sourceHash": source_hash,
            "lineRef": f"json:row:{row_index}",
        },
        "postedAt": occurred_at,
        "occurredAt": occurred_at,
        "amount": {"value": str(amount_value), "currency": currency},
        "direction": direction,
        "merchant": merchant,
        "description": description,
        "category": {"id": category_id, "confidence": 0.4 if category_id != "uncategorized" else 0.0, "reason": "bank_json_import"},
        "tags": ["integration"],
        "confidence": {
            "extraction": 1.0,
            "normalization": 0.95,
            "categorization": 0.4 if category_id != "uncategorized" else 0.0,
        },
        "links": {"receiptDocId": None, "billDocId": None},
        "createdAt": utc_now_iso(),
    }


def import_bank_json_path(
    layout: Layout,
    path: str | Path,
    *,
    commit: bool,
    copy_into_sources: bool,
    default_currency: str,
    sample: int,
    max_rows: int | None,
) -> dict[str, Any]:
    doc = register_file(
        layout.sources_dir,
        layout.sources_index_path,
        path,
        copy_into_sources=copy_into_sources,
        source_type="bank_json",
    )
    doc_id = doc["docId"]

    rows = _parse_records(path)
    if max_rows is not None and max_rows >= 0:
        rows = rows[: int(max_rows)]

    imported = 0
    skipped = 0
    errors = 0
    samples: list[dict[str, Any]] = []

    for i, row in enumerate(rows, start=1):
        try:
            tx = _row_to_tx(doc_id=doc_id, row_index=i, row=row, default_currency=default_currency)
        except Exception:
            errors += 1
            continue

        if commit:
            h = str((tx.get("source") or {}).get("sourceHash") or "")
            if has_source_hash(layout, doc_id=doc_id, source_hash=h):
                skipped += 1
                continue
            append_jsonl(layout.transactions_path, tx)
            imported += 1
        else:
            if len(samples) < int(sample):
                samples.append(tx)

    return {
        "mode": "commit" if commit else "dry-run",
        "docId": doc_id,
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "sample": samples,
    }
