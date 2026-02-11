from __future__ import annotations

from collections import defaultdict
from typing import Any

from .layout import Layout
from .ledger import LedgerView, filter_by_date_range, load_ledger
from .storage import ensure_dir, write_json
from .timeutil import utc_now_iso
from .txutil import tx_date, tx_month


def build_daily_monthly_caches(
    layout: Layout,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    include_deleted: bool = False,
) -> dict[str, Any]:
    view: LedgerView = load_ledger(layout, include_deleted=include_deleted)
    txs = filter_by_date_range(view.transactions, from_date=from_date, to_date=to_date)

    daily: dict[str, list[dict[str, Any]]] = defaultdict(list)
    monthly: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tx in txs:
        d = tx_date(tx)
        if d:
            daily[d].append(tx)
        m = tx_month(tx)
        if m:
            monthly[m].append(tx)

    ensure_dir(layout.ledger_dir / "daily")
    ensure_dir(layout.ledger_dir / "monthly")

    generated_at = utc_now_iso()
    for d, items in daily.items():
        write_json(layout.ledger_dir / "daily" / f"{d}.json", {"date": d, "generatedAt": generated_at, "transactions": items})
    for m, items in monthly.items():
        write_json(
            layout.ledger_dir / "monthly" / f"{m}.json",
            {"month": m, "generatedAt": generated_at, "transactions": items},
        )

    summary = {
        "generatedAt": generated_at,
        "fromDate": from_date,
        "toDate": to_date,
        "days": sorted(daily.keys()),
        "months": sorted(monthly.keys()),
        "appliedCorrections": view.applied_corrections,
        "deletedTxCount": len(view.deleted_tx_ids),
    }
    write_json(layout.ledger_dir / "summary.json", summary)

    return summary

