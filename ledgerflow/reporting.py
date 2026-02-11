from __future__ import annotations

import calendar
import re
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .alerts import alerts_for_date
from .layout import Layout
from .ledger import filter_by_date_range, filter_by_month, load_ledger
from .money import decimal_from_any, fmt_decimal
from .storage import ensure_dir, read_json, write_json
from .timeutil import utc_now_iso
from .txutil import tx_amount_decimal, tx_category_confidence, tx_category_id, tx_currency, tx_date, tx_merchant, tx_source_type


def _load_category_labels(layout: Layout) -> dict[str, str]:
    cfg = read_json(layout.categories_path, {"categories": []})
    out: dict[str, str] = {}
    for c in cfg.get("categories", []):
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip()
        label = str(c.get("label") or "").strip()
        if cid and label:
            out[cid] = label
    return out


def _sum_currency(txs: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    acc: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"spend": Decimal("0"), "income": Decimal("0"), "net": Decimal("0")})
    for tx in txs:
        ccy = tx_currency(tx) or "UNK"
        amt = tx_amount_decimal(tx)
        if amt < 0:
            acc[ccy]["spend"] += -amt
        else:
            acc[ccy]["income"] += amt
        acc[ccy]["net"] += amt
    return {ccy: {k: fmt_decimal(v) for k, v in vals.items()} for ccy, vals in acc.items()}


def _top_categories(txs: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for tx in txs:
        amt = tx_amount_decimal(tx)
        if amt >= 0:
            continue
        ccy = tx_currency(tx) or "UNK"
        cat = tx_category_id(tx) or "uncategorized"
        totals[(ccy, cat)] += -amt
    out = []
    for (ccy, cat), val in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]:
        out.append({"currency": ccy, "categoryId": cat, "value": fmt_decimal(val)})
    return out


def _top_merchants(txs: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for tx in txs:
        amt = tx_amount_decimal(tx)
        if amt >= 0:
            continue
        ccy = tx_currency(tx) or "UNK"
        m = tx_merchant(tx) or "UNKNOWN"
        key = (ccy, m)
        if key not in totals:
            totals[key] = {"value": Decimal("0"), "count": 0}
        totals[key]["value"] += -amt
        totals[key]["count"] += 1
    out = []
    for (ccy, m), data in sorted(totals.items(), key=lambda kv: kv[1]["value"], reverse=True)[:limit]:
        out.append({"currency": ccy, "merchant": m, "value": fmt_decimal(data["value"]), "count": int(data["count"])})
    return out


def _review_queue(txs: list[dict[str, Any]], *, cat_conf_threshold: float = 0.60) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for tx in txs:
        cat_id = tx_category_id(tx) or "uncategorized"
        cat_conf = tx_category_confidence(tx)
        merchant = str(tx.get("merchant") or "").strip()
        desc = str(tx.get("description") or "").strip()

        reasons: list[str] = []
        if cat_id in ("", "uncategorized"):
            reasons.append("uncategorized")
        if cat_conf < cat_conf_threshold:
            reasons.append(f"low_category_confidence:{cat_conf:.2f}")
        if not merchant and not desc:
            reasons.append("missing_merchant_and_description")

        if reasons:
            items.append(
                {
                    "txId": tx.get("txId"),
                    "date": tx_date(tx),
                    "amount": tx.get("amount"),
                    "merchant": tx_merchant(tx),
                    "categoryId": cat_id,
                    "reasons": reasons,
                }
            )
    return items


def _merchant_score(a: str, b: str) -> float:
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

    aa = norm(a)
    bb = norm(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    if aa in bb or bb in aa:
        return 0.8
    ta = set(aa.split())
    tb = set(bb.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _possible_manual_bank_duplicates(
    all_txs: list[dict[str, Any]],
    *,
    day: str,
    max_days_diff: int = 1,
    amount_tolerance: Decimal = Decimal("0.01"),
) -> dict[str, str]:
    """
    Return mapping manualTxId -> bankTxId for likely duplicates.
    """
    day_dt = datetime.strptime(day, "%Y-%m-%d").date()
    manual = [t for t in all_txs if tx_source_type(t) == "manual" and tx_date(t) == day]
    banks = [t for t in all_txs if tx_source_type(t) == "bank_csv"]

    out: dict[str, str] = {}
    for mtx in manual:
        mid = str(mtx.get("txId") or "")
        if not mid:
            continue
        mam = tx_amount_decimal(mtx)
        if mam >= 0:
            continue
        mamt = -mam
        mccy = tx_currency(mtx)
        mmer = tx_merchant(mtx)

        best = None
        best_score = -1.0
        for btx in banks:
            bd_s = tx_date(btx)
            if not bd_s:
                continue
            try:
                bd = datetime.strptime(bd_s, "%Y-%m-%d").date()
            except ValueError:
                continue
            if abs((bd - day_dt).days) > max_days_diff:
                continue
            if mccy and tx_currency(btx) and tx_currency(btx) != mccy:
                continue
            bam = tx_amount_decimal(btx)
            if bam >= 0:
                continue
            if abs((-bam) - mamt) > amount_tolerance:
                continue

            score = 0.5 + 0.5 * _merchant_score(mmer, tx_merchant(btx))
            if score > best_score:
                best_score = score
                best = btx

        if best and best_score >= 0.65:
            bid = str(best.get("txId") or "")
            if bid:
                out[mid] = bid
    return out


def _month_bounds(month: str) -> tuple[str, str]:
    y, m = month.split("-")
    year = int(y)
    mon = int(m)
    last = calendar.monthrange(year, mon)[1]
    return f"{year:04d}-{mon:02d}-01", f"{year:04d}-{mon:02d}-{last:02d}"


def _detect_recurring(
    txs: list[dict[str, Any]],
    *,
    min_occurrences: int = 3,
    spacing_days: tuple[int, int] = (25, 35),
) -> list[dict[str, Any]]:
    # Group by (merchant, currency) for debits, keep amounts to detect drift.
    groups: dict[tuple[str, str], list[tuple[str, Decimal]]] = defaultdict(list)
    for tx in txs:
        amt = tx_amount_decimal(tx)
        if amt >= 0:
            continue
        merchant = tx_merchant(tx)
        if not merchant:
            continue
        ccy = tx_currency(tx) or "UNK"
        d = tx_date(tx)
        if not d:
            continue
        groups[(merchant.lower(), ccy)].append((d, -amt))

    out: list[dict[str, Any]] = []
    for (m, ccy), items in groups.items():
        items2 = sorted(items, key=lambda x: x[0])
        if len(items2) < min_occurrences:
            continue

        dates = [d for d, _ in items2]
        amounts = [a for _, a in items2]

        # Find the most recent window that satisfies spacing.
        best_window = None
        for end in range(min_occurrences, len(dates) + 1):
            window_dates = dates[end - min_occurrences : end]
            ok = True
            for a, b in zip(window_dates, window_dates[1:]):
                da = datetime.strptime(a, "%Y-%m-%d").date()
                db = datetime.strptime(b, "%Y-%m-%d").date()
                delta = (db - da).days
                if delta < spacing_days[0] or delta > spacing_days[1]:
                    ok = False
                    break
            if ok:
                best_window = (end - min_occurrences, end)
        if best_window is None:
            continue

        i0, i1 = best_window
        recent_dates = dates[i0:i1]
        recent_amounts = amounts[i0:i1]
        last_amount = recent_amounts[-1]
        prev_amount = recent_amounts[-2] if len(recent_amounts) >= 2 else None

        drift = None
        drift_pct = None
        if prev_amount is not None and prev_amount != 0:
            drift = last_amount - prev_amount
            drift_pct = (drift / prev_amount) * Decimal("100")

        out.append(
            {
                "merchant": m,
                "currency": ccy,
                "occurrences": len(items2),
                "recentDates": recent_dates,
                "recentAmounts": [fmt_decimal(x) for x in recent_amounts],
                "lastAmount": fmt_decimal(last_amount),
                "prevAmount": fmt_decimal(prev_amount) if prev_amount is not None else None,
                "drift": fmt_decimal(drift) if drift is not None else None,
                "driftPct": fmt_decimal(drift_pct) if drift_pct is not None else None,
            }
        )

    out.sort(key=lambda r: int(r.get("occurrences") or 0), reverse=True)
    return out[:50]


def daily_report_data(layout: Layout, *, date: str) -> dict[str, Any]:
    view = load_ledger(layout, include_deleted=False)
    day_txs = [tx for tx in view.transactions if tx_date(tx) == date]

    d = datetime.strptime(date, "%Y-%m-%d").date()
    from_7 = (d - timedelta(days=6)).isoformat()
    to_7 = d.isoformat()
    rolling_txs = filter_by_date_range(view.transactions, from_date=from_7, to_date=to_7)

    categories = _load_category_labels(layout)

    data = {
        "date": date,
        "generatedAt": utc_now_iso(),
        "summary": _sum_currency(day_txs),
        "topCategoriesToday": _top_categories(day_txs),
        "topMerchantsToday": _top_merchants(day_txs),
        "rolling7d": {
            "from": from_7,
            "to": to_7,
            "summary": _sum_currency(rolling_txs),
            "topCategories": _top_categories(rolling_txs),
        },
        "reviewQueue": _review_queue(day_txs),
        "possibleDuplicates": _possible_manual_bank_duplicates(view.transactions, day=date),
        "alerts": alerts_for_date(layout, date),
        "categoryLabels": categories,
    }
    return data


def render_daily_report_md(data: dict[str, Any]) -> str:
    date = data["date"]
    cat_labels = data.get("categoryLabels") or {}

    lines: list[str] = []
    lines.append(f"# Daily Report: {date}")
    lines.append("")

    lines.append("## Summary")
    for ccy, vals in sorted((data.get("summary") or {}).items()):
        lines.append(f"- {ccy}: spend {vals['spend']}, income {vals['income']}, net {vals['net']}")
    lines.append("")

    lines.append("## Top Categories (Today)")
    top_cats = data.get("topCategoriesToday") or []
    if not top_cats:
        lines.append("- (none)")
    else:
        for item in top_cats:
            cid = item["categoryId"]
            label = cat_labels.get(cid, cid)
            lines.append(f"- {label} ({item['currency']}): {item['value']}")
    lines.append("")

    lines.append("## Top Merchants (Today)")
    top_merch = data.get("topMerchantsToday") or []
    if not top_merch:
        lines.append("- (none)")
    else:
        for item in top_merch:
            lines.append(f"- {item['merchant']} ({item['currency']}): {item['value']} ({item['count']} tx)")
    lines.append("")

    roll = data.get("rolling7d") or {}
    lines.append(f"## Rolling 7 Days ({roll.get('from')} to {roll.get('to')})")
    for ccy, vals in sorted((roll.get("summary") or {}).items()):
        lines.append(f"- {ccy}: spend {vals['spend']}, income {vals['income']}, net {vals['net']}")
    lines.append("")
    lines.append("### Top Categories (Rolling 7 Days)")
    roll_cats = roll.get("topCategories") or []
    if not roll_cats:
        lines.append("- (none)")
    else:
        for item in roll_cats:
            cid = item["categoryId"]
            label = cat_labels.get(cid, cid)
            lines.append(f"- {label} ({item['currency']}): {item['value']}")
    lines.append("")

    lines.append("## Review Queue")
    rq = data.get("reviewQueue") or []
    if not rq:
        lines.append("- (none)")
    else:
        for item in rq[:50]:
            tx_id = item.get("txId") or ""
            merchant = item.get("merchant") or ""
            reasons = ", ".join(item.get("reasons") or [])
            amt = item.get("amount") or {}
            val = amt.get("value") if isinstance(amt, dict) else ""
            ccy = amt.get("currency") if isinstance(amt, dict) else ""
            lines.append(f"- {tx_id}: {merchant} {val} {ccy} ({reasons})")
    lines.append("")

    lines.append("## Possible Duplicates (Manual vs Bank)")
    dup = data.get("possibleDuplicates") or {}
    if not dup:
        lines.append("- (none)")
    else:
        for mid, bid in list(dup.items())[:50]:
            lines.append(f"- manual {mid} may duplicate bank {bid}")
    lines.append("")

    lines.append("## Alerts (Today)")
    al = data.get("alerts") or []
    if not al:
        lines.append("- (none)")
    else:
        for evt in al[-50:]:
            lines.append(f"- [{evt.get('ruleId')}] {evt.get('message')}")
    lines.append("")

    return "\n".join(lines)


def write_daily_report(layout: Layout, *, date: str) -> dict[str, str]:
    ensure_dir(layout.reports_dir / "daily")
    data = daily_report_data(layout, date=date)
    md = render_daily_report_md(data)

    md_path = layout.reports_dir / "daily" / f"{date}.md"
    json_path = layout.reports_dir / "daily" / f"{date}.json"
    md_path.write_text(md, encoding="utf-8")
    write_json(json_path, data)
    return {"md": str(md_path), "json": str(json_path)}


def monthly_report_data(layout: Layout, *, month: str) -> dict[str, Any]:
    view = load_ledger(layout, include_deleted=False)
    month_txs = filter_by_month(view.transactions, month)

    start, end = _month_bounds(month)

    # For anomalies/recurring, use trailing 6 months including current.
    y, m = month.split("-")
    year = int(y)
    mon = int(m)
    months: list[str] = []
    yy, mm = year, mon
    for _ in range(6):
        months.append(f"{yy:04d}-{mm:02d}")
        mm -= 1
        if mm == 0:
            yy -= 1
            mm = 12
    months = list(reversed(months))
    trailing_txs: list[dict[str, Any]] = []
    for mo in months:
        trailing_txs.extend(filter_by_month(view.transactions, mo))

    recurring = _detect_recurring(trailing_txs)

    # Manual vs imported ratio.
    by_source: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "spend": Decimal("0"), "income": Decimal("0")})
    for tx in month_txs:
        st = tx_source_type(tx) or "unknown"
        by_source[st]["count"] += 1
        amt = tx_amount_decimal(tx)
        if amt < 0:
            by_source[st]["spend"] += -amt
        else:
            by_source[st]["income"] += amt

    source_summary = []
    for st, data in sorted(by_source.items(), key=lambda kv: kv[1]["count"], reverse=True):
        source_summary.append(
            {
                "sourceType": st,
                "count": int(data["count"]),
                "spend": fmt_decimal(data["spend"]),
                "income": fmt_decimal(data["income"]),
            }
        )

    # Anomalies/spikes: compare to previous 3 months average.
    prev_months = months[:-1][-3:]
    prev_tx = []
    for mo in prev_months:
        prev_tx.extend(filter_by_month(view.transactions, mo))

    def cat_totals(txs: list[dict[str, Any]]) -> dict[tuple[str, str], Decimal]:
        t: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
        for tx in txs:
            amt = tx_amount_decimal(tx)
            if amt >= 0:
                continue
            t[(tx_currency(tx) or "UNK", tx_category_id(tx) or "uncategorized")] += -amt
        return t

    cur_cats = cat_totals(month_txs)
    prev_cats = cat_totals(prev_tx)
    spikes = []
    for key, cur_val in cur_cats.items():
        prev_val = prev_cats.get(key, Decimal("0"))
        avg = (prev_val / Decimal(str(len(prev_months)))) if prev_months else Decimal("0")
        # Basic heuristic thresholds.
        if avg > 0 and cur_val > avg * Decimal("1.5") and (cur_val - avg) > Decimal("50"):
            spikes.append({"currency": key[0], "categoryId": key[1], "current": fmt_decimal(cur_val), "avgPrev3": fmt_decimal(avg)})
    spikes.sort(key=lambda r: Decimal(r["current"]) - Decimal(r["avgPrev3"]), reverse=True)

    # Merchant spikes.
    def merchant_totals(txs: list[dict[str, Any]]) -> dict[tuple[str, str], Decimal]:
        t: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
        for tx in txs:
            amt = tx_amount_decimal(tx)
            if amt >= 0:
                continue
            t[(tx_currency(tx) or "UNK", tx_merchant(tx) or "UNKNOWN")] += -amt
        return t

    cur_merch = merchant_totals(month_txs)
    prev_merch = merchant_totals(prev_tx)
    merch_spikes = []
    for key, cur_val in cur_merch.items():
        prev_val = prev_merch.get(key, Decimal("0"))
        avg = (prev_val / Decimal(str(len(prev_months)))) if prev_months else Decimal("0")
        if avg > 0 and cur_val > avg * Decimal("1.5") and (cur_val - avg) > Decimal("50"):
            merch_spikes.append({"currency": key[0], "merchant": key[1], "current": fmt_decimal(cur_val), "avgPrev3": fmt_decimal(avg)})
    merch_spikes.sort(key=lambda r: Decimal(r["current"]) - Decimal(r["avgPrev3"]), reverse=True)

    data = {
        "month": month,
        "from": start,
        "to": end,
        "generatedAt": utc_now_iso(),
        "summary": _sum_currency(month_txs),
        "categoryBreakdown": _top_categories(month_txs, limit=50),
        "merchantTop": _top_merchants(month_txs, limit=50),
        "recurring": recurring,
        "categorySpikes": spikes[:25],
        "merchantSpikes": merch_spikes[:25],
        "sourceSummary": source_summary,
        "categoryLabels": _load_category_labels(layout),
    }
    return data


def render_monthly_report_md(data: dict[str, Any]) -> str:
    month = data["month"]
    cat_labels = data.get("categoryLabels") or {}

    lines: list[str] = []
    lines.append(f"# Monthly Report: {month}")
    lines.append("")

    lines.append("## Summary")
    for ccy, vals in sorted((data.get("summary") or {}).items()):
        lines.append(f"- {ccy}: spend {vals['spend']}, income {vals['income']}, net {vals['net']}")
    lines.append("")

    lines.append("## Category Breakdown")
    for item in (data.get("categoryBreakdown") or [])[:20]:
        cid = item["categoryId"]
        label = cat_labels.get(cid, cid)
        lines.append(f"- {label} ({item['currency']}): {item['value']}")
    lines.append("")

    lines.append("## Top Merchants")
    for item in (data.get("merchantTop") or [])[:20]:
        lines.append(f"- {item['merchant']} ({item['currency']}): {item['value']} ({item['count']} tx)")
    lines.append("")

    lines.append("## Recurring Charges (Detected)")
    rec = data.get("recurring") or []
    if not rec:
        lines.append("- (none)")
    else:
        for r in rec[:25]:
            drift = ""
            if r.get("drift") and r.get("prevAmount") and r.get("driftPct"):
                drift = f" (drift: {r['prevAmount']} -> {r['lastAmount']} = {r['drift']} / {r['driftPct']}%)"
            lines.append(
                f"- {r['merchant']} ({r['currency']}): recent {', '.join(r['recentAmounts'])} on {', '.join(r['recentDates'])} (occurrences: {r['occurrences']}){drift}"
            )
    lines.append("")

    lines.append("## Category Spikes (Vs Avg Prev 3 Months)")
    spikes = data.get("categorySpikes") or []
    if not spikes:
        lines.append("- (none)")
    else:
        for s in spikes[:25]:
            cid = s["categoryId"]
            label = cat_labels.get(cid, cid)
            lines.append(f"- {label} ({s['currency']}): current {s['current']} vs avg {s['avgPrev3']}")
    lines.append("")

    lines.append("## Merchant Spikes (Vs Avg Prev 3 Months)")
    msp = data.get("merchantSpikes") or []
    if not msp:
        lines.append("- (none)")
    else:
        for s in msp[:25]:
            lines.append(f"- {s['merchant']} ({s['currency']}): current {s['current']} vs avg {s['avgPrev3']}")
    lines.append("")

    lines.append("## Manual vs Imported")
    for s in data.get("sourceSummary") or []:
        lines.append(f"- {s['sourceType']}: {s['count']} tx (spend {s['spend']}, income {s['income']})")
    lines.append("")

    return "\n".join(lines)


def write_monthly_report(layout: Layout, *, month: str) -> dict[str, str]:
    ensure_dir(layout.reports_dir / "monthly")
    data = monthly_report_data(layout, month=month)
    md = render_monthly_report_md(data)

    md_path = layout.reports_dir / "monthly" / f"{month}.md"
    json_path = layout.reports_dir / "monthly" / f"{month}.json"
    md_path.write_text(md, encoding="utf-8")
    write_json(json_path, data)
    return {"md": str(md_path), "json": str(json_path)}
