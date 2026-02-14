from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .integration_bank_json import import_bank_json_records
from .layout import Layout


_CONNECTORS: dict[str, dict[str, str]] = {
    "plaid": {
        "id": "plaid",
        "title": "Plaid Transactions JSON",
        "description": "Imports Plaid transaction payloads (transactions list).",
    },
    "wise": {
        "id": "wise",
        "title": "Wise Activity JSON",
        "description": "Imports Wise-like activity exports with amount/date/merchant fields.",
    },
}


def list_connectors() -> list[dict[str, str]]:
    return [dict(v) for _, v in sorted(_CONNECTORS.items(), key=lambda kv: kv[0])]


def _parse_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as e:
        raise ValueError(f"invalid numeric value: {value!r}") from e


def _tx_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("transactions"), list):
            return [x for x in payload.get("transactions") if isinstance(x, dict)]
        if isinstance(payload.get("activity"), list):
            return [x for x in payload.get("activity") if isinstance(x, dict)]
    raise ValueError("connector payload must contain a transaction list")


def _norm_plaid(rows: list[dict[str, Any]], *, default_currency: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        date = str(row.get("date") or row.get("authorized_date") or "").strip()
        if not date:
            continue
        amount = _parse_decimal(row.get("amount") or "0")
        # Plaid amounts are usually positive for spending. Normalize to signed ledger convention.
        signed = -amount
        currency = str(row.get("iso_currency_code") or row.get("unofficial_currency_code") or default_currency)
        merchant = str(row.get("merchant_name") or row.get("name") or "").strip()
        desc = str(row.get("name") or merchant)
        cat = "uncategorized"
        pfc = row.get("personal_finance_category") if isinstance(row.get("personal_finance_category"), dict) else {}
        primary = str(pfc.get("primary") or "").strip().lower()
        if primary in ("food_and_drink", "groceries"):
            cat = "groceries"
        elif primary in ("travel", "transportation"):
            cat = "transport"
        elif primary in ("income",):
            cat = "income"

        out.append(
            {
                "date": date,
                "amount": str(signed),
                "currency": currency,
                "merchant": merchant,
                "description": desc,
                "category": cat,
            }
        )
    return out


def _norm_wise(rows: list[dict[str, Any]], *, default_currency: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        date = str(row.get("date") or row.get("createdOn") or row.get("bookingDate") or "").strip()
        if not date:
            continue
        if isinstance(row.get("amount"), dict):
            amount = _parse_decimal((row.get("amount") or {}).get("value"))
            currency = str((row.get("amount") or {}).get("currency") or default_currency)
        else:
            amount = _parse_decimal(row.get("amount") or row.get("amountValue") or "0")
            currency = str(row.get("currency") or default_currency)
        merchant = str(row.get("merchant") or row.get("counterparty") or row.get("name") or "").strip()
        desc = str(row.get("description") or row.get("details") or merchant)
        out.append(
            {
                "date": date,
                "amount": str(amount),
                "currency": currency,
                "merchant": merchant,
                "description": desc,
                "category": "uncategorized",
            }
        )
    return out


def normalize_connector_payload(connector: str, payload: Any, *, default_currency: str) -> list[dict[str, Any]]:
    name = str(connector or "").strip().lower()
    rows = _tx_list(payload)
    if name == "plaid":
        return _norm_plaid(rows, default_currency=default_currency)
    if name == "wise":
        return _norm_wise(rows, default_currency=default_currency)
    raise ValueError(f"unsupported connector: {name}")


def import_connector_path(
    layout: Layout,
    *,
    connector: str,
    path: str | Path,
    commit: bool,
    copy_into_sources: bool,
    default_currency: str,
    sample: int,
    max_rows: int | None,
) -> dict[str, Any]:
    p = Path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    normalized = normalize_connector_payload(connector, payload, default_currency=default_currency)
    return import_bank_json_records(
        layout,
        normalized,
        source_path=p,
        source_type=f"connector_{str(connector).strip().lower()}",
        commit=commit,
        copy_into_sources=copy_into_sources,
        default_currency=default_currency,
        sample=sample,
        max_rows=max_rows,
        mapping=None,
    )
