from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .ids import new_id
from .layout import Layout
from .ledger import load_ledger
from .money import decimal_from_any
from .storage import append_jsonl, read_json
from .timeutil import utc_now_iso
from .txutil import tx_amount_decimal, tx_currency, tx_date, tx_merchant, tx_source_type


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _merchant_score(a: str, b: str) -> float:
    aa = _norm_text(a)
    bb = _norm_text(b)
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
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union


def _already_linked_receipts(txs: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for tx in txs:
        links = tx.get("links") or {}
        if not isinstance(links, dict):
            continue
        rid = links.get("receiptDocId")
        if isinstance(rid, str) and rid:
            out.add(rid)
    return out


def _already_linked_bills(txs: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for tx in txs:
        links = tx.get("links") or {}
        if not isinstance(links, dict):
            continue
        bid = links.get("billDocId")
        if isinstance(bid, str) and bid:
            out.add(bid)
    return out


def _candidate_bank_txs(txs: list[dict[str, Any]], *, skip_link_fields: list[str] | None = None) -> list[dict[str, Any]]:
    skip_link_fields = skip_link_fields or []
    out = []
    for tx in txs:
        if tx_source_type(tx) != "bank_csv":
            continue
        links = tx.get("links") or {}
        if isinstance(links, dict):
            skip = False
            for f in skip_link_fields:
                if links.get(f):
                    skip = True
                    break
            if skip:
                continue
        out.append(tx)
    return out


def _load_receipt_docs(layout: Layout) -> list[dict[str, Any]]:
    idx = read_json(layout.sources_index_path, {"version": 1, "docs": []})
    docs = idx.get("docs", [])
    if not isinstance(docs, list):
        return []
    out = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        if str(d.get("sourceType") or "") != "receipt":
            continue
        doc_id = str(d.get("docId") or "")
        if not doc_id:
            continue
        parse_path = layout.sources_dir / doc_id / "parse.json"
        if not parse_path.exists():
            continue
        parsed = read_json(parse_path, {})
        if not isinstance(parsed, dict):
            continue
        out.append({"doc": d, "parse": parsed})
    return out


def _load_bill_docs(layout: Layout) -> list[dict[str, Any]]:
    idx = read_json(layout.sources_index_path, {"version": 1, "docs": []})
    docs = idx.get("docs", [])
    if not isinstance(docs, list):
        return []
    out = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        if str(d.get("sourceType") or "") != "bill":
            continue
        doc_id = str(d.get("docId") or "")
        if not doc_id:
            continue
        parse_path = layout.sources_dir / doc_id / "parse.json"
        if not parse_path.exists():
            continue
        parsed = read_json(parse_path, {})
        if not isinstance(parsed, dict):
            continue
        out.append({"doc": d, "parse": parsed})
    return out


def link_receipts_to_bank(
    layout: Layout,
    *,
    max_days_diff: int = 3,
    amount_tolerance: str = "0.01",
    commit: bool = True,
) -> dict[str, Any]:
    view = load_ledger(layout, include_deleted=False)
    txs = view.transactions

    linked_receipts = _already_linked_receipts(txs)
    bank_txs = _candidate_bank_txs(txs, skip_link_fields=["receiptDocId"])

    tol = decimal_from_any(amount_tolerance)
    receipts = _load_receipt_docs(layout)

    created = 0
    skipped = 0
    attempted = 0

    for item in receipts:
        doc = item["doc"]
        parsed = item["parse"]
        doc_id = str(doc.get("docId") or "")
        if not doc_id or doc_id in linked_receipts:
            skipped += 1
            continue

        attempted += 1

        r_date = str(parsed.get("date") or "")
        r_total = parsed.get("total") or {}
        if not r_date or not isinstance(r_total, dict):
            continue

        try:
            rd = datetime.strptime(r_date, "%Y-%m-%d").date()
        except ValueError:
            continue

        try:
            total = decimal_from_any(r_total.get("value"))
        except Exception:
            continue

        ccy = str(r_total.get("currency") or "")
        merchant = str(parsed.get("merchant") or "").strip()

        best = None
        best_score = -1.0
        for tx in bank_txs:
            td_s = tx_date(tx)
            if not td_s:
                continue
            try:
                td = datetime.strptime(td_s, "%Y-%m-%d").date()
            except ValueError:
                continue
            if abs((td - rd).days) > max_days_diff:
                continue

            if ccy and tx_currency(tx) and tx_currency(tx) != ccy:
                continue

            amt = tx_amount_decimal(tx)
            if amt >= 0:
                continue
            if abs((-amt) - total) > tol:
                continue

            score = 0.5  # base score for date+amount match
            score += _merchant_score(merchant, tx_merchant(tx)) * 0.5
            if score > best_score:
                best_score = score
                best = tx

        if not best:
            continue

        tx_id = str(best.get("txId") or "")
        if not tx_id:
            continue

        patch: dict[str, Any] = {"links": {"receiptDocId": doc_id}}
        # If the tx has no merchant, fill it from receipt to improve UX.
        if not str(best.get("merchant") or "").strip() and merchant:
            patch["merchant"] = merchant
        # Tag for UI/reporting.
        tags = best.get("tags")
        if isinstance(tags, list) and "receipt-linked" not in tags:
            patch["tags"] = tags + ["receipt-linked"]
        elif tags is None:
            patch["tags"] = ["receipt-linked"]

        evt = {
            "eventId": new_id("evt"),
            "txId": tx_id,
            "type": "patch",
            "patch": patch,
            "reason": "auto_link_receipt",
            "at": utc_now_iso(),
        }

        if commit:
            append_jsonl(layout.corrections_path, evt)
            created += 1
            linked_receipts.add(doc_id)

    return {"attempted": attempted, "created": created, "skipped": skipped, "commit": commit}


def link_bills_to_bank(
    layout: Layout,
    *,
    max_days_diff: int = 7,
    amount_tolerance: str = "0.01",
    commit: bool = True,
) -> dict[str, Any]:
    view = load_ledger(layout, include_deleted=False)
    txs = view.transactions

    linked_bills = _already_linked_bills(txs)
    bank_txs = _candidate_bank_txs(txs, skip_link_fields=["billDocId"])
    tol = decimal_from_any(amount_tolerance)
    bills = _load_bill_docs(layout)

    created = 0
    skipped = 0
    attempted = 0

    for item in bills:
        doc = item["doc"]
        parsed = item["parse"]
        doc_id = str(doc.get("docId") or "")
        if not doc_id or doc_id in linked_bills:
            skipped += 1
            continue

        attempted += 1

        amt_obj = parsed.get("amount") or {}
        if not isinstance(amt_obj, dict):
            continue
        try:
            amount = decimal_from_any(amt_obj.get("value"))
        except Exception:
            continue
        ccy = str(amt_obj.get("currency") or "")

        vendor = str(parsed.get("vendor") or "").strip()
        anchor = str(parsed.get("dueDate") or parsed.get("date") or "")
        if not anchor:
            continue
        try:
            ad = datetime.strptime(anchor, "%Y-%m-%d").date()
        except ValueError:
            continue

        best = None
        best_score = -1.0
        for tx in bank_txs:
            td_s = tx_date(tx)
            if not td_s:
                continue
            try:
                td = datetime.strptime(td_s, "%Y-%m-%d").date()
            except ValueError:
                continue
            if abs((td - ad).days) > max_days_diff:
                continue
            if ccy and tx_currency(tx) and tx_currency(tx) != ccy:
                continue
            tamt = tx_amount_decimal(tx)
            if tamt >= 0:
                continue
            if abs((-tamt) - amount) > tol:
                continue
            score = 0.5 + 0.5 * _merchant_score(vendor, tx_merchant(tx))
            if score > best_score:
                best_score = score
                best = tx

        if not best:
            continue
        tx_id = str(best.get("txId") or "")
        if not tx_id:
            continue

        patch: dict[str, Any] = {"links": {"billDocId": doc_id}}
        evt = {
            "eventId": new_id("evt"),
            "txId": tx_id,
            "type": "patch",
            "patch": patch,
            "reason": "auto_link_bill",
            "at": utc_now_iso(),
        }
        if commit:
            append_jsonl(layout.corrections_path, evt)
            created += 1
            linked_bills.add(doc_id)

    return {"attempted": attempted, "created": created, "skipped": skipped, "commit": commit}
