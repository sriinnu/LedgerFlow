from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Iterable

from .jsonl import iter_jsonl
from .layout import Layout
from .txutil import tx_date, tx_month


def deep_merge_inplace(dst: dict[str, Any], patch: dict[str, Any]) -> None:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge_inplace(dst[k], v)  # type: ignore[index]
        else:
            dst[k] = v


@dataclass(frozen=True)
class LedgerView:
    transactions: list[dict[str, Any]]
    deleted_tx_ids: set[str]
    applied_corrections: int


def load_transactions_raw(layout: Layout) -> list[dict[str, Any]]:
    return list(iter_jsonl(layout.transactions_path) or [])


def load_corrections_raw(layout: Layout) -> list[dict[str, Any]]:
    return list(iter_jsonl(layout.corrections_path) or [])


def apply_corrections(
    transactions: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    *,
    include_deleted: bool = False,
) -> LedgerView:
    # Keep original order, but apply corrections by txId deterministically in event order.
    tx_list: list[dict[str, Any]] = []
    tx_by_id: dict[str, dict[str, Any]] = {}
    for tx in transactions:
        tx_id = tx.get("txId")
        if not isinstance(tx_id, str) or not tx_id:
            continue
        tx_copy = copy.deepcopy(tx)
        tx_list.append(tx_copy)
        tx_by_id[tx_id] = tx_copy

    deleted: set[str] = set()
    applied = 0

    for evt in corrections:
        tx_id = evt.get("txId")
        if not isinstance(tx_id, str) or not tx_id:
            continue
        if tx_id not in tx_by_id:
            continue

        evt_type = str(evt.get("type") or "patch")
        if evt_type == "patch":
            patch = evt.get("patch")
            if isinstance(patch, dict) and patch:
                deep_merge_inplace(tx_by_id[tx_id], patch)
                applied += 1
        elif evt_type in ("tombstone", "delete"):
            deleted.add(tx_id)
            applied += 1
        else:
            # Unknown correction type: ignore (forward-compatible).
            continue

    if include_deleted:
        return LedgerView(transactions=tx_list, deleted_tx_ids=deleted, applied_corrections=applied)

    filtered = [tx for tx in tx_list if str(tx.get("txId") or "") not in deleted]
    return LedgerView(transactions=filtered, deleted_tx_ids=deleted, applied_corrections=applied)


def load_ledger(
    layout: Layout,
    *,
    include_deleted: bool = False,
) -> LedgerView:
    txs = load_transactions_raw(layout)
    evts = load_corrections_raw(layout)
    return apply_corrections(txs, evts, include_deleted=include_deleted)


def filter_by_date_range(
    txs: Iterable[dict[str, Any]],
    *,
    from_date: str | None,
    to_date: str | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tx in txs:
        d = tx_date(tx)
        if not d:
            continue
        if from_date and d < from_date:
            continue
        if to_date and d > to_date:
            continue
        out.append(tx)
    return out


def filter_by_month(txs: Iterable[dict[str, Any]], month: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tx in txs:
        m = tx_month(tx)
        if m == month:
            out.append(tx)
    return out

