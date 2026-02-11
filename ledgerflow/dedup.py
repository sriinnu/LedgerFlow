from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .ids import new_id
from .layout import Layout
from .ledger import filter_by_date_range, load_ledger
from .money import decimal_from_any
from .storage import append_jsonl
from .timeutil import utc_now_iso
from .txutil import tx_amount_decimal, tx_currency, tx_date, tx_merchant, tx_source_type


def _norm(s: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _merchant_score(a: str, b: str) -> float:
    aa = _norm(a)
    bb = _norm(b)
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


def mark_manual_duplicates_against_bank(
    layout: Layout,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    max_days_diff: int = 1,
    amount_tolerance: str = "0.01",
    commit: bool = True,
) -> dict[str, Any]:
    view = load_ledger(layout, include_deleted=False)
    txs = filter_by_date_range(view.transactions, from_date=from_date, to_date=to_date)

    manual = [t for t in txs if tx_source_type(t) == "manual"]
    bank = [t for t in txs if tx_source_type(t) == "bank_csv"]

    tol = decimal_from_any(amount_tolerance)

    created = 0
    skipped = 0
    matches = 0

    for mtx in manual:
        mid = str(mtx.get("txId") or "")
        if not mid:
            continue
        mdate_s = tx_date(mtx)
        if not mdate_s:
            continue
        try:
            mdate = datetime.strptime(mdate_s, "%Y-%m-%d").date()
        except ValueError:
            continue

        mam = tx_amount_decimal(mtx)
        if mam >= 0:
            continue
        mamt = -mam
        mccy = tx_currency(mtx)
        mmer = tx_merchant(mtx)

        best = None
        best_score = -1.0
        for btx in bank:
            bdate_s = tx_date(btx)
            if not bdate_s:
                continue
            try:
                bdate = datetime.strptime(bdate_s, "%Y-%m-%d").date()
            except ValueError:
                continue
            if abs((bdate - mdate).days) > max_days_diff:
                continue
            if mccy and tx_currency(btx) and tx_currency(btx) != mccy:
                continue
            bam = tx_amount_decimal(btx)
            if bam >= 0:
                continue
            if abs((-bam) - mamt) > tol:
                continue
            score = 0.5 + 0.5 * _merchant_score(mmer, tx_merchant(btx))
            if score > best_score:
                best_score = score
                best = btx

        if not best or best_score < 0.65:
            continue
        matches += 1

        tags = mtx.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        if "duplicate_candidate" in tags:
            skipped += 1
            continue

        patch = {"tags": tags + ["duplicate_candidate"], "links": {"duplicateOfTxId": str(best.get("txId") or "")}}
        evt = {
            "eventId": new_id("evt"),
            "txId": mid,
            "type": "patch",
            "patch": patch,
            "reason": "auto_dedup_manual_vs_bank",
            "at": utc_now_iso(),
        }

        if commit:
            append_jsonl(layout.corrections_path, evt)
            created += 1

    return {"matches": matches, "created": created, "skipped": skipped, "commit": commit}

