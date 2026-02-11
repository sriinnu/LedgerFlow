from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .layout import Layout
from .ledger import filter_by_date_range, load_ledger
from .storage import ensure_dir
from .txutil import tx_amount_decimal, tx_category_id, tx_currency, tx_date, tx_merchant, tx_source_type


def export_transactions_csv(
    layout: Layout,
    *,
    out_path: str | Path,
    from_date: str | None = None,
    to_date: str | None = None,
    include_deleted: bool = False,
) -> str:
    view = load_ledger(layout, include_deleted=include_deleted)
    txs = filter_by_date_range(view.transactions, from_date=from_date, to_date=to_date)

    out = Path(out_path)
    ensure_dir(out.parent)

    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "occurredAt",
                "postedAt",
                "amount",
                "currency",
                "direction",
                "merchant",
                "description",
                "categoryId",
                "sourceType",
                "txId",
                "receiptDocId",
                "billDocId",
            ]
        )
        for tx in txs:
            links = tx.get("links") or {}
            if not isinstance(links, dict):
                links = {}
            w.writerow(
                [
                    tx.get("occurredAt") or "",
                    tx.get("postedAt") or "",
                    str((tx.get("amount") or {}).get("value") or ""),
                    tx_currency(tx),
                    tx.get("direction") or "",
                    tx_merchant(tx),
                    tx.get("description") or "",
                    tx_category_id(tx),
                    tx_source_type(tx),
                    tx.get("txId") or "",
                    links.get("receiptDocId") or "",
                    links.get("billDocId") or "",
                ]
            )

    return str(out)

