from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from .layout import Layout
from .ledger import filter_by_date_range, filter_by_month, load_ledger
from .money import fmt_decimal
from .storage import ensure_dir, write_json
from .timeutil import utc_now_iso
from .txutil import daterange, tx_amount_decimal, tx_category_id, tx_currency, tx_date, tx_merchant


def build_series(layout: Layout, *, from_date: str, to_date: str) -> dict[str, Any]:
    view = load_ledger(layout, include_deleted=False)
    txs = filter_by_date_range(view.transactions, from_date=from_date, to_date=to_date)

    # Per-day sums (by currency).
    per_day: dict[str, dict[str, dict[str, Decimal]]] = defaultdict(lambda: defaultdict(lambda: {"spend": Decimal("0"), "income": Decimal("0"), "net": Decimal("0")}))
    for tx in txs:
        d = tx_date(tx)
        if not d:
            continue
        ccy = tx_currency(tx) or "UNK"
        amt = tx_amount_decimal(tx)
        if amt < 0:
            per_day[d][ccy]["spend"] += -amt
        else:
            per_day[d][ccy]["income"] += amt
        per_day[d][ccy]["net"] += amt

    points: list[dict[str, Any]] = []
    for d in daterange(from_date, to_date):
        # If multiple currencies exist, emit per-currency entries for the same day.
        if d not in per_day:
            points.append({"t": d, "spend": "0", "income": "0", "net": "0", "currency": None})
            continue
        cur_map = per_day[d]
        if len(cur_map) == 1:
            ccy, vals = next(iter(cur_map.items()))
            points.append(
                {
                    "t": d,
                    "spend": fmt_decimal(vals["spend"]),
                    "income": fmt_decimal(vals["income"]),
                    "net": fmt_decimal(vals["net"]),
                    "currency": ccy,
                }
            )
        else:
            for ccy, vals in sorted(cur_map.items()):
                points.append(
                    {
                        "t": d,
                        "spend": fmt_decimal(vals["spend"]),
                        "income": fmt_decimal(vals["income"]),
                        "net": fmt_decimal(vals["net"]),
                        "currency": ccy,
                    }
                )

    return {
        "granularity": "day",
        "from": from_date,
        "to": to_date,
        "generatedAt": utc_now_iso(),
        "points": points,
    }


def write_series(layout: Layout, *, from_date: str, to_date: str) -> str:
    ensure_dir(layout.charts_dir)
    data = build_series(layout, from_date=from_date, to_date=to_date)
    name = f"series.{from_date}_{to_date}.json"
    path = layout.charts_dir / name
    write_json(path, data)
    return str(path)


def build_category_breakdown_month(layout: Layout, *, month: str) -> dict[str, Any]:
    view = load_ledger(layout, include_deleted=False)
    txs = filter_by_month(view.transactions, month)

    totals: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))  # (ccy, category)
    for tx in txs:
        amt = tx_amount_decimal(tx)
        if amt >= 0:
            continue
        ccy = tx_currency(tx) or "UNK"
        cat = tx_category_id(tx) or "uncategorized"
        totals[(ccy, cat)] += -amt

    out_totals = []
    for (ccy, cat), val in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
        out_totals.append({"currency": ccy, "categoryId": cat, "value": fmt_decimal(val)})

    return {"month": month, "generatedAt": utc_now_iso(), "totals": out_totals}


def write_category_breakdown_month(layout: Layout, *, month: str) -> str:
    ensure_dir(layout.charts_dir)
    data = build_category_breakdown_month(layout, month=month)
    path = layout.charts_dir / f"category_breakdown.{month}.json"
    write_json(path, data)
    return str(path)


def build_merchant_top_month(layout: Layout, *, month: str, limit: int = 25) -> dict[str, Any]:
    view = load_ledger(layout, include_deleted=False)
    txs = filter_by_month(view.transactions, month)

    totals: dict[tuple[str, str], dict[str, Any]] = {}  # (ccy, merchant) -> {value, count}
    for tx in txs:
        amt = tx_amount_decimal(tx)
        if amt >= 0:
            continue
        merchant = tx_merchant(tx) or "UNKNOWN"
        ccy = tx_currency(tx) or "UNK"
        key = (ccy, merchant)
        if key not in totals:
            totals[key] = {"value": Decimal("0"), "count": 0}
        totals[key]["value"] += -amt
        totals[key]["count"] += 1

    top = []
    for (ccy, merchant), data in sorted(totals.items(), key=lambda kv: kv[1]["value"], reverse=True)[:limit]:
        top.append({"currency": ccy, "merchant": merchant, "value": fmt_decimal(data["value"]), "count": int(data["count"])})

    return {"month": month, "generatedAt": utc_now_iso(), "top": top}


def write_merchant_top_month(layout: Layout, *, month: str, limit: int = 25) -> str:
    ensure_dir(layout.charts_dir)
    data = build_merchant_top_month(layout, month=month, limit=limit)
    path = layout.charts_dir / f"merchant_top.{month}.json"
    write_json(path, data)
    return str(path)

