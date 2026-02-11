from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from .ids import new_id
from .layout import Layout
from .ledger import filter_by_date_range, load_ledger
from .money import decimal_from_any, fmt_decimal
from .storage import append_jsonl, read_json, write_json
from .timeutil import utc_now_iso
from .txutil import tx_amount_decimal, tx_category_confidence, tx_category_id, tx_date, tx_merchant, tx_source_type


def _default_state() -> dict[str, Any]:
    return {"version": 1, "lastRun": None, "rules": {}}


def load_rules(layout: Layout) -> dict[str, Any]:
    return read_json(layout.alert_rules_path, {"currency": "USD", "rules": []})


def load_state(layout: Layout) -> dict[str, Any]:
    return read_json(layout.alerts_dir / "state.json", _default_state())


def save_state(layout: Layout, state: dict[str, Any]) -> None:
    write_json(layout.alerts_dir / "state.json", state)


def _period_key(period: str, at: date) -> str:
    if period == "day":
        return at.isoformat()
    if period == "month":
        return f"{at.year:04d}-{at.month:02d}"
    if period == "week":
        iso_year, iso_week, _ = at.isocalendar()
        return f"{iso_year:04d}-W{iso_week:02d}"
    raise ValueError(f"Unknown period: {period}")


def _period_bounds(period: str, at: date) -> tuple[date, date]:
    if period == "day":
        return at, at
    if period == "month":
        start = date(at.year, at.month, 1)
        # next month start - 1 day
        if at.month == 12:
            next_month = date(at.year + 1, 1, 1)
        else:
            next_month = date(at.year, at.month + 1, 1)
        end = next_month - timedelta(days=1)
        return start, end
    if period == "week":
        # ISO week: Monday is 1
        start = at - timedelta(days=at.isoweekday() - 1)
        end = start + timedelta(days=6)
        return start, end
    raise ValueError(f"Unknown period: {period}")


def _sum_category_spend(txs: list[dict[str, Any]], category_id: str) -> tuple[Decimal, list[str]]:
    total = Decimal("0")
    ids: list[str] = []
    for tx in txs:
        if tx_category_id(tx) != category_id:
            continue
        amt = tx_amount_decimal(tx)
        if amt >= 0:
            continue
        total += -amt
        tx_id = tx.get("txId")
        if isinstance(tx_id, str):
            ids.append(tx_id)
    return total, ids


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return start, next_month - timedelta(days=1)


def _period_sequence(period: str, at: date, lookback_periods: int) -> list[tuple[str, date, date]]:
    if lookback_periods < 1:
        lookback_periods = 1
    out: list[tuple[str, date, date]] = []
    if period == "day":
        for i in range(0, lookback_periods + 1):
            d = at - timedelta(days=i)
            out.append((_period_key("day", d), d, d))
        return out
    if period == "week":
        start, _ = _period_bounds("week", at)
        for i in range(0, lookback_periods + 1):
            s = start - timedelta(days=7 * i)
            e = s + timedelta(days=6)
            out.append((_period_key("week", s), s, e))
        return out
    if period == "month":
        total = at.year * 12 + (at.month - 1)
        for i in range(0, lookback_periods + 1):
            idx = total - i
            y = idx // 12
            m = idx % 12 + 1
            s, e = _month_bounds(y, m)
            out.append((f"{y:04d}-{m:02d}", s, e))
        return out
    raise ValueError(f"Unknown period: {period}")


def _is_debit(tx: dict[str, Any]) -> bool:
    return tx_amount_decimal(tx) < 0


def _merchant_spend(
    txs: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str], Decimal], dict[tuple[str, str], str], dict[tuple[str, str], list[str]]]:
    totals: dict[tuple[str, str], Decimal] = {}
    display: dict[tuple[str, str], str] = {}
    tx_ids: dict[tuple[str, str], list[str]] = {}
    for tx in txs:
        if not _is_debit(tx):
            continue
        merchant = tx_merchant(tx).strip()
        if not merchant:
            continue
        ccy = str((tx.get("amount") or {}).get("currency") or "UNK")
        key = (merchant.lower(), ccy)
        totals[key] = totals.get(key, Decimal("0")) + (-tx_amount_decimal(tx))
        if key not in display:
            display[key] = merchant
        tx_id = tx.get("txId")
        if isinstance(tx_id, str):
            tx_ids.setdefault(key, []).append(tx_id)
    return totals, display, tx_ids


def _recurring_groups(
    txs: list[dict[str, Any]],
) -> dict[tuple[str, str], list[tuple[str, Decimal]]]:
    groups: dict[tuple[str, str], list[tuple[str, Decimal]]] = {}
    for tx in txs:
        amt = tx_amount_decimal(tx)
        if amt >= 0:
            continue
        merchant = tx_merchant(tx).strip()
        d = tx_date(tx)
        if not merchant or not d:
            continue
        ccy = str((tx.get("amount") or {}).get("currency") or "UNK")
        key = (merchant.lower(), ccy)
        groups.setdefault(key, []).append((d, -amt))
    for key in list(groups.keys()):
        groups[key] = sorted(groups[key], key=lambda x: x[0])
    return groups


def run_alerts(
    layout: Layout,
    *,
    at_date: str,
    commit: bool = True,
) -> dict[str, Any]:
    at = datetime.strptime(at_date, "%Y-%m-%d").date()

    rules_cfg = load_rules(layout)
    state = load_state(layout)

    view = load_ledger(layout, include_deleted=False)

    events: list[dict[str, Any]] = []

    for rule in rules_cfg.get("rules", []):
        if not isinstance(rule, dict):
            continue

        rule_id = str(rule.get("id") or "").strip()
        rule_type = str(rule.get("type") or "").strip()
        if not rule_id or not rule_type:
            continue

        state_rule = (state.get("rules") or {}).get(rule_id) or {}
        if not isinstance(state_rule, dict):
            state_rule = {}

        if rule_type == "category_budget":
            category_id = str(rule.get("categoryId") or "").strip()
            period = str(rule.get("period") or "").strip()
            limit = decimal_from_any(rule.get("limit"))

            if not category_id or not period:
                continue

            key = _period_key(period, at)
            if state_rule.get("lastTriggeredPeriodKey") == key:
                continue

            start, end = _period_bounds(period, at)
            scoped = filter_by_date_range(
                view.transactions,
                from_date=start.isoformat(),
                to_date=end.isoformat(),
            )
            spend, tx_ids = _sum_category_spend(scoped, category_id)
            if spend <= limit:
                continue

            msg = f"{category_id} spend {fmt_decimal(spend)} exceeded limit {fmt_decimal(limit)} for {period} {key}"
            event = {
                "eventId": new_id("alrt"),
                "ruleId": rule_id,
                "type": rule_type,
                "period": period,
                "periodKey": key,
                "scopeDate": at_date,
                "at": utc_now_iso(),
                "data": {
                    "categoryId": category_id,
                    "limit": str(limit),
                    "value": str(spend),
                    "txIds": tx_ids[:500],
                },
                "message": msg,
            }
            events.append(event)

            if commit:
                append_jsonl(layout.alerts_dir / "events.jsonl", event)
                state.setdefault("rules", {}).setdefault(rule_id, {})["lastTriggeredPeriodKey"] = key
                state["rules"][rule_id]["lastValue"] = str(spend)

        elif rule_type == "recurring_new":
            # Minimal implementation: look for a merchant/amount debit pattern repeating within spacingDays.
            min_occ = int(rule.get("minOccurrences") or 3)
            spacing = rule.get("spacingDays") or [25, 35]
            if not isinstance(spacing, list) or len(spacing) != 2:
                spacing = [25, 35]
            spacing_min, spacing_max = int(spacing[0]), int(spacing[1])

            key = _period_key("month", at)
            if state_rule.get("lastTriggeredPeriodKey") == key:
                continue

            # Look back 180 days for candidates.
            start = at - timedelta(days=180)
            scoped = filter_by_date_range(view.transactions, from_date=start.isoformat(), to_date=at.isoformat())

            # Group by (merchant, amount, currency) for debits.
            groups: dict[tuple[str, str, str], list[str]] = {}
            for tx in scoped:
                amt = tx_amount_decimal(tx)
                if amt >= 0:
                    continue
                merchant = tx_merchant(tx)
                if not merchant:
                    continue
                ccy = str((tx.get("amount") or {}).get("currency") or "")
                key2 = (merchant.lower(), str(-amt), ccy)
                groups.setdefault(key2, []).append(tx_date(tx))

            new_found = []
            for (m, amt_s, ccy), dates in groups.items():
                dates2 = sorted({d for d in dates if d})
                if len(dates2) < min_occ:
                    continue
                # Check last min_occ occurrences spacing.
                tail = dates2[-min_occ:]
                ok = True
                for a, b in zip(tail, tail[1:]):
                    da = datetime.strptime(a, "%Y-%m-%d").date()
                    db = datetime.strptime(b, "%Y-%m-%d").date()
                    delta = (db - da).days
                    if delta < spacing_min or delta > spacing_max:
                        ok = False
                        break
                if not ok:
                    continue

                # "New" heuristic: no occurrence before the first of the tail within the lookback window.
                first_tail = datetime.strptime(tail[0], "%Y-%m-%d").date()
                prior = [d for d in dates2 if datetime.strptime(d, "%Y-%m-%d").date() < first_tail]
                if prior:
                    continue
                new_found.append({"merchant": m, "amount": amt_s, "currency": ccy, "dates": tail})

            if not new_found:
                continue

            msg = f"New recurring charges detected: {len(new_found)}"
            event = {
                "eventId": new_id("alrt"),
                "ruleId": rule_id,
                "type": rule_type,
                "period": "month",
                "periodKey": key,
                "scopeDate": at_date,
                "at": utc_now_iso(),
                "data": {"items": new_found[:50]},
                "message": msg,
            }
            events.append(event)

            if commit:
                append_jsonl(layout.alerts_dir / "events.jsonl", event)
                state.setdefault("rules", {}).setdefault(rule_id, {})["lastTriggeredPeriodKey"] = key

        elif rule_type == "merchant_spike":
            period = str(rule.get("period") or "month").strip()
            lookback = int(rule.get("lookbackPeriods") or 3)
            multiplier = decimal_from_any(rule.get("multiplier") if "multiplier" in rule else "1.5")
            min_delta = decimal_from_any(rule.get("minDelta") if "minDelta" in rule else "50")
            merchant_filter = str(rule.get("merchant") or "").strip().lower()

            current_key = _period_key(period, at)
            if state_rule.get("lastTriggeredPeriodKey") == current_key:
                continue

            seq = _period_sequence(period, at, lookback)
            _, cur_start, cur_end = seq[0]
            current_txs = filter_by_date_range(view.transactions, from_date=cur_start.isoformat(), to_date=cur_end.isoformat())
            cur_totals, cur_display, cur_ids = _merchant_spend(current_txs)

            prev_maps: list[dict[tuple[str, str], Decimal]] = []
            for _, s, e in seq[1:]:
                txs_p = filter_by_date_range(view.transactions, from_date=s.isoformat(), to_date=e.isoformat())
                p_totals, _, _ = _merchant_spend(txs_p)
                prev_maps.append(p_totals)

            items = []
            for key2, cur_val in cur_totals.items():
                mer_l, ccy = key2
                if merchant_filter and mer_l != merchant_filter:
                    continue
                prev_sum = Decimal("0")
                for pm in prev_maps:
                    prev_sum += pm.get(key2, Decimal("0"))
                prev_avg = prev_sum / Decimal(str(len(prev_maps) or 1))
                if prev_avg <= 0:
                    continue
                if cur_val <= (prev_avg * multiplier):
                    continue
                if (cur_val - prev_avg) <= min_delta:
                    continue
                items.append(
                    {
                        "merchant": cur_display.get(key2, mer_l),
                        "currency": ccy,
                        "current": str(cur_val),
                        "avgPrev": str(prev_avg),
                        "delta": str(cur_val - prev_avg),
                        "txIds": (cur_ids.get(key2) or [])[:500],
                    }
                )

            if not items:
                continue
            msg = f"Merchant spend spike detected: {len(items)}"
            event = {
                "eventId": new_id("alrt"),
                "ruleId": rule_id,
                "type": rule_type,
                "period": period,
                "periodKey": current_key,
                "scopeDate": at_date,
                "at": utc_now_iso(),
                "data": {"items": items[:100]},
                "message": msg,
            }
            events.append(event)
            if commit:
                append_jsonl(layout.alerts_dir / "events.jsonl", event)
                state.setdefault("rules", {}).setdefault(rule_id, {})["lastTriggeredPeriodKey"] = current_key

        elif rule_type == "recurring_changed":
            min_occ = int(rule.get("minOccurrences") or 3)
            spacing = rule.get("spacingDays") or [25, 35]
            if not isinstance(spacing, list) or len(spacing) != 2:
                spacing = [25, 35]
            spacing_min, spacing_max = int(spacing[0]), int(spacing[1])
            min_delta = decimal_from_any(rule.get("minDelta") if "minDelta" in rule else "5")
            min_delta_pct = decimal_from_any(rule.get("minDeltaPct") if "minDeltaPct" in rule else "5")

            key = _period_key("month", at)
            if state_rule.get("lastTriggeredPeriodKey") == key:
                continue

            start = at - timedelta(days=240)
            scoped = filter_by_date_range(view.transactions, from_date=start.isoformat(), to_date=at.isoformat())
            groups = _recurring_groups(scoped)

            changed_items = []
            for (merchant_l, ccy), items in groups.items():
                if len(items) < min_occ:
                    continue
                dates = [d for d, _ in items]
                amounts = [a for _, a in items]

                best_tail = None
                for end_idx in range(min_occ, len(dates) + 1):
                    tail_dates = dates[end_idx - min_occ : end_idx]
                    ok = True
                    for a_s, b_s in zip(tail_dates, tail_dates[1:]):
                        da = datetime.strptime(a_s, "%Y-%m-%d").date()
                        db = datetime.strptime(b_s, "%Y-%m-%d").date()
                        delta_days = (db - da).days
                        if delta_days < spacing_min or delta_days > spacing_max:
                            ok = False
                            break
                    if ok:
                        best_tail = (end_idx - min_occ, end_idx)
                if best_tail is None:
                    continue

                i0, i1 = best_tail
                recent_amts = amounts[i0:i1]
                if len(recent_amts) < 2:
                    continue
                prev_amt = recent_amts[-2]
                last_amt = recent_amts[-1]
                delta = last_amt - prev_amt
                delta_pct = (delta / prev_amt * Decimal("100")) if prev_amt != 0 else Decimal("0")
                if abs(delta) < min_delta and abs(delta_pct) < min_delta_pct:
                    continue

                changed_items.append(
                    {
                        "merchant": merchant_l,
                        "currency": ccy,
                        "prevAmount": str(prev_amt),
                        "lastAmount": str(last_amt),
                        "delta": str(delta),
                        "deltaPct": str(delta_pct),
                        "recentDates": dates[i0:i1],
                    }
                )

            if not changed_items:
                continue

            msg = f"Recurring charges changed: {len(changed_items)}"
            event = {
                "eventId": new_id("alrt"),
                "ruleId": rule_id,
                "type": rule_type,
                "period": "month",
                "periodKey": key,
                "scopeDate": at_date,
                "at": utc_now_iso(),
                "data": {"items": changed_items[:100]},
                "message": msg,
            }
            events.append(event)

            if commit:
                append_jsonl(layout.alerts_dir / "events.jsonl", event)
                state.setdefault("rules", {}).setdefault(rule_id, {})["lastTriggeredPeriodKey"] = key

        elif rule_type == "cash_heavy_day":
            key = _period_key("day", at)
            if state_rule.get("lastTriggeredPeriodKey") == key:
                continue

            limit = decimal_from_any(rule.get("limit") if "limit" in rule else "150")
            day_txs = filter_by_date_range(view.transactions, from_date=at.isoformat(), to_date=at.isoformat())
            spend = Decimal("0")
            tx_ids: list[str] = []
            for tx in day_txs:
                if not _is_debit(tx):
                    continue
                tags = tx.get("tags")
                is_cash_tag = isinstance(tags, list) and ("cash" in tags)
                if tx_source_type(tx) != "manual" and not is_cash_tag:
                    continue
                spend += -tx_amount_decimal(tx)
                tx_id = tx.get("txId")
                if isinstance(tx_id, str):
                    tx_ids.append(tx_id)
            if spend <= limit:
                continue

            msg = f"Cash-heavy day spend {fmt_decimal(spend)} exceeded limit {fmt_decimal(limit)}"
            event = {
                "eventId": new_id("alrt"),
                "ruleId": rule_id,
                "type": rule_type,
                "period": "day",
                "periodKey": key,
                "scopeDate": at_date,
                "at": utc_now_iso(),
                "data": {"limit": str(limit), "value": str(spend), "txIds": tx_ids[:500]},
                "message": msg,
            }
            events.append(event)
            if commit:
                append_jsonl(layout.alerts_dir / "events.jsonl", event)
                state.setdefault("rules", {}).setdefault(rule_id, {})["lastTriggeredPeriodKey"] = key

        elif rule_type == "unclassified_spend":
            period = str(rule.get("period") or "day").strip()
            key = _period_key(period, at)
            if state_rule.get("lastTriggeredPeriodKey") == key:
                continue
            conf_below = float(rule.get("categoryConfidenceBelow") if "categoryConfidenceBelow" in rule else 0.6)
            limit = decimal_from_any(rule.get("limit") if "limit" in rule else "50")
            start, end = _period_bounds(period, at)
            scoped = filter_by_date_range(view.transactions, from_date=start.isoformat(), to_date=end.isoformat())

            spend = Decimal("0")
            tx_ids: list[str] = []
            for tx in scoped:
                if not _is_debit(tx):
                    continue
                cat_id = tx_category_id(tx)
                cat_conf = tx_category_confidence(tx)
                if cat_id not in ("", "uncategorized") and cat_conf >= conf_below:
                    continue
                spend += -tx_amount_decimal(tx)
                tx_id = tx.get("txId")
                if isinstance(tx_id, str):
                    tx_ids.append(tx_id)

            if spend <= limit:
                continue

            msg = f"Unclassified spend {fmt_decimal(spend)} exceeded limit {fmt_decimal(limit)} for {period} {key}"
            event = {
                "eventId": new_id("alrt"),
                "ruleId": rule_id,
                "type": rule_type,
                "period": period,
                "periodKey": key,
                "scopeDate": at_date,
                "at": utc_now_iso(),
                "data": {"limit": str(limit), "value": str(spend), "txIds": tx_ids[:500], "categoryConfidenceBelow": conf_below},
                "message": msg,
            }
            events.append(event)
            if commit:
                append_jsonl(layout.alerts_dir / "events.jsonl", event)
                state.setdefault("rules", {}).setdefault(rule_id, {})["lastTriggeredPeriodKey"] = key

        else:
            continue

    state["lastRun"] = utc_now_iso()
    if commit:
        save_state(layout, state)

    return {"at": at_date, "events": events, "eventCount": len(events), "commit": commit}


def alerts_for_date(layout: Layout, ymd: str) -> list[dict[str, Any]]:
    p = layout.alerts_dir / "events.jsonl"
    if not p.exists():
        return []
    out = []
    for evt in (json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()):
        if not isinstance(evt, dict):
            continue
        at = str(evt.get("at") or "")
        if at.startswith(ymd):
            out.append(evt)
    return out
