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
from .txutil import tx_amount_decimal, tx_category_id, tx_date, tx_merchant, tx_source_type


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

