from __future__ import annotations

from typing import Any

from .layout import Layout
from .ledger import load_ledger
from .manual import correction_event
from .storage import append_jsonl, read_json
from .timeutil import parse_ymd, utc_now_iso
from .txutil import tx_category_confidence, tx_category_id, tx_date, tx_merchant, tx_source_type


def _float_or_zero(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except Exception:
        return 0.0


def _tx_review_item(tx: dict[str, Any], *, cat_conf_threshold: float) -> dict[str, Any] | None:
    reasons: list[str] = []
    cat_id = tx_category_id(tx) or "uncategorized"
    cat_conf = tx_category_confidence(tx)
    merchant = str(tx.get("merchant") or "").strip()
    desc = str(tx.get("description") or "").strip()
    tags = tx.get("tags") if isinstance(tx.get("tags"), list) else []

    if cat_id in ("", "uncategorized"):
        reasons.append("uncategorized")
    if cat_conf < cat_conf_threshold:
        reasons.append(f"low_category_confidence:{cat_conf:.2f}")
    if not merchant and not desc:
        reasons.append("missing_merchant_and_description")
    if "duplicate_candidate" in tags:
        reasons.append("duplicate_candidate")

    if not reasons:
        return None

    return {
        "kind": "transaction",
        "txId": tx.get("txId"),
        "date": tx_date(tx),
        "merchant": tx_merchant(tx),
        "categoryId": cat_id,
        "categoryConfidence": round(cat_conf, 2),
        "sourceType": tx_source_type(tx),
        "amount": tx.get("amount"),
        "reasons": reasons,
    }


def _source_parse_review_items(
    layout: Layout,
    *,
    date: str | None,
    parse_conf_threshold: float,
) -> list[dict[str, Any]]:
    idx = read_json(layout.sources_index_path, {"version": 1, "docs": []})
    docs = idx.get("docs")
    if not isinstance(docs, list):
        return []

    items: list[dict[str, Any]] = []
    for doc in reversed(docs):
        if not isinstance(doc, dict):
            continue
        doc_id = str(doc.get("docId") or "").strip()
        if not doc_id:
            continue

        parse_path = layout.sources_dir / doc_id / "parse.json"
        if not parse_path.exists():
            continue
        parsed = read_json(parse_path, {})
        if not isinstance(parsed, dict) or not parsed:
            continue

        parsed_date = str(parsed.get("date") or "").strip()
        if date and parsed_date and parsed_date != date:
            continue

        ptype = str(parsed.get("type") or "")
        conf = _float_or_zero(parsed.get("confidence"))
        reasons: list[str] = []
        if conf < parse_conf_threshold:
            reasons.append(f"low_parse_confidence:{conf:.2f}")

        if ptype == "receipt":
            if not parsed.get("merchant"):
                reasons.append("missing_merchant")
            if not parsed.get("total"):
                reasons.append("missing_total")
        if ptype == "bill":
            if not parsed.get("vendor"):
                reasons.append("missing_vendor")
            if not parsed.get("amount"):
                reasons.append("missing_amount")

        if not reasons:
            continue

        items.append(
            {
                "kind": "source_parse",
                "docId": doc_id,
                "sourceType": str(doc.get("sourceType") or ""),
                "date": parsed_date or None,
                "confidence": round(conf, 2),
                "template": ((parsed.get("parser") or {}).get("template") if isinstance(parsed.get("parser"), dict) else None),
                "reasons": reasons,
            }
        )
    return items


def review_queue(
    layout: Layout,
    *,
    date: str | None = None,
    limit: int = 200,
    cat_conf_threshold: float = 0.60,
    parse_conf_threshold: float = 0.75,
) -> dict[str, Any]:
    if date:
        parse_ymd(date)

    view = load_ledger(layout, include_deleted=False)
    txs = [tx for tx in view.transactions if (tx_date(tx) == date if date else True)]

    tx_items: list[dict[str, Any]] = []
    for tx in txs:
        it = _tx_review_item(tx, cat_conf_threshold=cat_conf_threshold)
        if it is not None:
            tx_items.append(it)

    source_items = _source_parse_review_items(layout, date=date, parse_conf_threshold=parse_conf_threshold)
    items = tx_items + source_items
    items = items[: max(0, int(limit))]

    return {
        "generatedAt": utc_now_iso(),
        "date": date,
        "counts": {
            "transactions": len(tx_items),
            "sourceParses": len(source_items),
            "total": len(tx_items) + len(source_items),
        },
        "items": items,
    }


def resolve_review_transaction(layout: Layout, *, tx_id: str, patch: dict[str, Any], reason: str = "review_resolve") -> dict[str, Any]:
    tx_id = str(tx_id or "").strip()
    if not tx_id:
        raise ValueError("tx_id is required")
    if not isinstance(patch, dict) or not patch:
        raise ValueError("patch is required")
    if "occurredAt" in patch:
        parse_ymd(str(patch["occurredAt"]))
    evt = correction_event(tx_id, patch=patch, reason=reason)
    append_jsonl(layout.corrections_path, evt)
    return evt
