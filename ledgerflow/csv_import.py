from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .hashing import canonical_json_bytes, sha256_bytes
from .ids import new_id
from .timeutil import utc_now_iso


@dataclass(frozen=True)
class CsvMapping:
    date_col: str
    description_col: str | None = None
    amount_col: str | None = None
    debit_col: str | None = None
    credit_col: str | None = None
    currency_col: str | None = None


_COMMON_DATE_COLS = ["date", "transaction date", "posted date", "posting date"]
_COMMON_DESC_COLS = ["description", "details", "memo", "narration", "merchant", "payee"]
_COMMON_AMOUNT_COLS = ["amount", "transaction amount", "amt"]
_COMMON_DEBIT_COLS = ["debit", "withdrawal", "money out"]
_COMMON_CREDIT_COLS = ["credit", "deposit", "money in"]
_COMMON_CURRENCY_COLS = ["currency", "ccy"]


def _norm_header(h: str) -> str:
    return " ".join(h.strip().lower().replace("_", " ").split())


def infer_mapping(headers: list[str]) -> CsvMapping:
    norm = {_norm_header(h): h for h in headers}

    def pick(candidates: list[str]) -> str | None:
        for c in candidates:
            if c in norm:
                return norm[c]
        return None

    date_col = pick(_COMMON_DATE_COLS)
    if not date_col:
        raise ValueError("Could not infer date column. Use --date-col.")

    desc_col = pick(_COMMON_DESC_COLS)
    amount_col = pick(_COMMON_AMOUNT_COLS)
    debit_col = pick(_COMMON_DEBIT_COLS)
    credit_col = pick(_COMMON_CREDIT_COLS)
    currency_col = pick(_COMMON_CURRENCY_COLS)

    if not amount_col and not (debit_col or credit_col):
        raise ValueError("Could not infer amount columns. Use --amount-col or --debit-col/--credit-col.")

    return CsvMapping(
        date_col=date_col,
        description_col=desc_col,
        amount_col=amount_col,
        debit_col=debit_col,
        credit_col=credit_col,
        currency_col=currency_col,
    )


def parse_amount_text(value: str) -> Decimal:
    s = value.strip()
    if not s:
        raise ValueError("Empty amount")

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()

    # Remove currency symbols/spaces and common separators.
    s = s.replace(",", "")
    s = s.replace("$", "").replace("€", "").replace("£", "")

    # Some exports use trailing minus: 12.34-
    if s.endswith("-"):
        negative = True
        s = s[:-1].strip()

    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"Invalid amount: {value!r}") from e

    return -d if negative else d


def _parse_date_text(value: str, *, date_format: str | None, day_first: bool) -> str:
    s = value.strip()
    if not s:
        raise ValueError("Empty date")

    if date_format:
        from datetime import datetime

        return datetime.strptime(s, date_format).date().isoformat()

    # Try a few common formats. If ambiguous, prefer based on day_first.
    from datetime import datetime

    # ISO first.
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass

    # Slash dates.
    slash_fmts = ["%m/%d/%Y", "%d/%m/%Y"]
    if day_first:
        slash_fmts = ["%d/%m/%Y", "%m/%d/%Y"]
    for fmt in slash_fmts:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass

    raise ValueError(f"Unrecognized date: {value!r}. Provide --date-format.")


def read_csv_rows(path: str | Path, *, encoding: str = "utf-8-sig") -> tuple[list[str], list[dict[str, str]]]:
    p = Path(path)
    with p.open("r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows: list[dict[str, str]] = []
        for row in reader:
            # DictReader may return None for missing fields; normalize to "".
            rows.append({k: (v if v is not None else "") for k, v in row.items()})
        return headers, rows


def csv_row_to_tx(
    *,
    doc_id: str,
    row_index: int,
    row: dict[str, str],
    mapping: CsvMapping,
    default_currency: str,
    date_format: str | None,
    day_first: bool,
) -> dict[str, Any]:
    occurred_at = _parse_date_text(row.get(mapping.date_col, ""), date_format=date_format, day_first=day_first)
    posted_at = occurred_at

    currency = default_currency
    if mapping.currency_col:
        c = (row.get(mapping.currency_col) or "").strip()
        if c:
            currency = c

    description = ""
    if mapping.description_col:
        description = (row.get(mapping.description_col) or "").strip()

    amount: Decimal
    if mapping.amount_col:
        amount = parse_amount_text(row.get(mapping.amount_col, ""))
    else:
        debit_raw = row.get(mapping.debit_col, "") if mapping.debit_col else ""
        credit_raw = row.get(mapping.credit_col, "") if mapping.credit_col else ""
        debit = parse_amount_text(debit_raw or "0")
        credit = parse_amount_text(credit_raw or "0")
        # Convention: debit and credit are positive in exports; normalize to signed amount.
        amount = credit - debit

    direction = "debit" if amount < 0 else "credit"

    # Stable row hash for idempotency/dedup.
    row_hash_obj = {"docId": doc_id, "rowIndex": row_index, "row": row}
    source_hash = "sha256:" + sha256_bytes(canonical_json_bytes(row_hash_obj))

    return {
        "txId": new_id("tx"),
        "source": {
            "docId": doc_id,
            "sourceType": "bank_csv",
            "sourceHash": source_hash,
            "lineRef": f"csv:row:{row_index}",
        },
        "postedAt": posted_at,
        "occurredAt": occurred_at,
        # Keep value as a decimal string to avoid float rounding errors.
        "amount": {"value": str(amount), "currency": currency},
        "direction": direction,
        "merchant": "",
        "description": description,
        "category": {"id": "uncategorized", "confidence": 0.0, "reason": "not_categorized_yet"},
        "tags": [],
        "confidence": {
            "extraction": 1.0,
            "normalization": 1.0,
            "categorization": 0.0,
        },
        "links": {"receiptDocId": None, "billDocId": None},
        "createdAt": utc_now_iso(),
    }
