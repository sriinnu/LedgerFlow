from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .jsonl import iter_jsonl
from .layout import Layout, layout_for
from .storage import ensure_dir, read_json
from .timeutil import utc_now_iso

INDEX_SCHEMA_VERSION = 1


def _connect(db_path: str | Path) -> sqlite3.Connection:
    p = Path(db_path)
    ensure_dir(p.parent)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=OFF;")
    return conn


@contextmanager
def _session(db_path: str | Path) -> Any:
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_index_schema(db_path: str | Path) -> None:
    with _session(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sources (
                doc_id TEXT PRIMARY KEY,
                source_type TEXT,
                sha256 TEXT,
                original_path TEXT,
                stored_path TEXT,
                size INTEGER,
                added_at TEXT,
                raw_json TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                tx_id TEXT PRIMARY KEY,
                source_type TEXT,
                source_doc_id TEXT,
                source_hash TEXT,
                occurred_at TEXT,
                posted_at TEXT,
                month TEXT,
                amount_value TEXT,
                currency TEXT,
                direction TEXT,
                merchant TEXT,
                category_id TEXT,
                raw_json TEXT NOT NULL,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS corrections (
                event_id TEXT PRIMARY KEY,
                tx_id TEXT,
                event_type TEXT,
                at TEXT,
                raw_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sources_sha256 ON sources (sha256);
            CREATE INDEX IF NOT EXISTS idx_tx_source_doc_hash ON transactions (source_doc_id, source_hash);
            CREATE INDEX IF NOT EXISTS idx_tx_occurred_at ON transactions (occurred_at);
            CREATE INDEX IF NOT EXISTS idx_tx_month ON transactions (month);
            CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions (category_id);
            CREATE INDEX IF NOT EXISTS idx_tx_source_type ON transactions (source_type);
            CREATE INDEX IF NOT EXISTS idx_tx_deleted ON transactions (is_deleted);
            CREATE INDEX IF NOT EXISTS idx_corr_tx_id ON corrections (tx_id);
            """
        )
        conn.execute(
            """
            INSERT INTO meta(key, value) VALUES('index_schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(INDEX_SCHEMA_VERSION),),
        )


def _tx_fields(tx: dict[str, Any]) -> dict[str, Any]:
    src = tx.get("source") if isinstance(tx.get("source"), dict) else {}
    amt = tx.get("amount") if isinstance(tx.get("amount"), dict) else {}
    cat = tx.get("category") if isinstance(tx.get("category"), dict) else {}
    occurred_at = str(tx.get("occurredAt") or "")
    month = occurred_at[:7] if len(occurred_at) >= 7 else ""
    return {
        "tx_id": str(tx.get("txId") or ""),
        "source_type": str(src.get("sourceType") or ""),
        "source_doc_id": str(src.get("docId") or ""),
        "source_hash": str(src.get("sourceHash") or ""),
        "occurred_at": occurred_at,
        "posted_at": str(tx.get("postedAt") or ""),
        "month": month,
        "amount_value": str(amt.get("value") or ""),
        "currency": str(amt.get("currency") or ""),
        "direction": str(tx.get("direction") or ""),
        "merchant": str(tx.get("merchant") or ""),
        "category_id": str(cat.get("id") or ""),
        "raw_json": json.dumps(tx, ensure_ascii=False),
    }


def upsert_transaction(db_path: str | Path, tx: dict[str, Any], *, is_deleted: bool = False) -> None:
    fields = _tx_fields(tx)
    if not fields["tx_id"]:
        return
    now = utc_now_iso()
    ensure_index_schema(db_path)
    with _session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO transactions (
                tx_id, source_type, source_doc_id, source_hash, occurred_at, posted_at, month,
                amount_value, currency, direction, merchant, category_id, raw_json, is_deleted,
                created_at, updated_at
            ) VALUES (
                :tx_id, :source_type, :source_doc_id, :source_hash, :occurred_at, :posted_at, :month,
                :amount_value, :currency, :direction, :merchant, :category_id, :raw_json, :is_deleted,
                :created_at, :updated_at
            )
            ON CONFLICT(tx_id) DO UPDATE SET
                source_type=excluded.source_type,
                source_doc_id=excluded.source_doc_id,
                source_hash=excluded.source_hash,
                occurred_at=excluded.occurred_at,
                posted_at=excluded.posted_at,
                month=excluded.month,
                amount_value=excluded.amount_value,
                currency=excluded.currency,
                direction=excluded.direction,
                merchant=excluded.merchant,
                category_id=excluded.category_id,
                raw_json=excluded.raw_json,
                is_deleted=excluded.is_deleted,
                updated_at=excluded.updated_at
            """,
            {
                **fields,
                "is_deleted": 1 if is_deleted else 0,
                "created_at": now,
                "updated_at": now,
            },
        )


def _deep_merge_inplace(dst: dict[str, Any], patch: dict[str, Any]) -> None:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge_inplace(dst[k], v)  # type: ignore[index]
        else:
            dst[k] = v


def apply_correction_event(db_path: str | Path, evt: dict[str, Any]) -> None:
    event_id = str(evt.get("eventId") or "")
    tx_id = str(evt.get("txId") or "")
    if not event_id or not tx_id:
        return
    ensure_index_schema(db_path)
    with _session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO corrections(event_id, tx_id, event_type, at, raw_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                tx_id=excluded.tx_id,
                event_type=excluded.event_type,
                at=excluded.at,
                raw_json=excluded.raw_json
            """,
            (
                event_id,
                tx_id,
                str(evt.get("type") or ""),
                str(evt.get("at") or ""),
                json.dumps(evt, ensure_ascii=False),
            ),
        )

        row = conn.execute("SELECT raw_json, is_deleted FROM transactions WHERE tx_id = ?", (tx_id,)).fetchone()
        if row is None:
            return

        tx = json.loads(row["raw_json"])
        evt_type = str(evt.get("type") or "patch")

        if evt_type == "patch":
            patch = evt.get("patch")
            if isinstance(patch, dict):
                _deep_merge_inplace(tx, patch)
            fields = _tx_fields(tx)
            conn.execute(
                """
                UPDATE transactions
                SET source_type=:source_type,
                    source_doc_id=:source_doc_id,
                    source_hash=:source_hash,
                    occurred_at=:occurred_at,
                    posted_at=:posted_at,
                    month=:month,
                    amount_value=:amount_value,
                    currency=:currency,
                    direction=:direction,
                    merchant=:merchant,
                    category_id=:category_id,
                    raw_json=:raw_json,
                    updated_at=:updated_at
                WHERE tx_id=:tx_id
                """,
                {**fields, "updated_at": utc_now_iso()},
            )
        elif evt_type in ("tombstone", "delete"):
            conn.execute("UPDATE transactions SET is_deleted = 1, updated_at = ? WHERE tx_id = ?", (utc_now_iso(), tx_id))



def upsert_source(db_path: str | Path, doc: dict[str, Any]) -> None:
    doc_id = str(doc.get("docId") or "")
    if not doc_id:
        return
    ensure_index_schema(db_path)
    now = utc_now_iso()
    with _session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sources(doc_id, source_type, sha256, original_path, stored_path, size, added_at, raw_json, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                source_type=excluded.source_type,
                sha256=excluded.sha256,
                original_path=excluded.original_path,
                stored_path=excluded.stored_path,
                size=excluded.size,
                added_at=excluded.added_at,
                raw_json=excluded.raw_json,
                indexed_at=excluded.indexed_at
            """,
            (
                doc_id,
                str(doc.get("sourceType") or ""),
                str(doc.get("sha256") or ""),
                str(doc.get("originalPath") or ""),
                str(doc.get("storedPath") or ""),
                int(doc.get("size") or 0),
                str(doc.get("addedAt") or ""),
                json.dumps(doc, ensure_ascii=False),
                now,
            ),
        )


def _layout_from_jsonl_path(path: Path) -> Layout | None:
    if path.name not in ("transactions.jsonl", "corrections.jsonl"):
        return None
    if path.parent.name != "ledger":
        return None
    return layout_for(path.parent.parent)


def hook_after_append(path: str | Path, obj: Any) -> None:
    p = Path(path)
    layout = _layout_from_jsonl_path(p)
    if layout is None:
        return
    if not isinstance(obj, dict):
        return

    if p.name == "transactions.jsonl":
        upsert_transaction(layout.index_db_path, obj, is_deleted=False)
    elif p.name == "corrections.jsonl":
        apply_correction_event(layout.index_db_path, obj)


def hook_after_source_register(index_path: str | Path, doc: dict[str, Any]) -> None:
    p = Path(index_path)
    if p.name != "index.json" or p.parent.name != "sources":
        return
    layout = layout_for(p.parent.parent)
    upsert_source(layout.index_db_path, doc)


def rebuild_index(layout: Layout) -> dict[str, Any]:
    ensure_index_schema(layout.index_db_path)
    with _session(layout.index_db_path) as conn:
        conn.execute("DELETE FROM corrections")
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM sources")

    tx_count = 0
    evt_count = 0
    src_count = 0

    for tx in iter_jsonl(layout.transactions_path) or []:
        if isinstance(tx, dict):
            upsert_transaction(layout.index_db_path, tx, is_deleted=False)
            tx_count += 1

    for evt in iter_jsonl(layout.corrections_path) or []:
        if isinstance(evt, dict):
            apply_correction_event(layout.index_db_path, evt)
            evt_count += 1

    idx = read_json(layout.sources_index_path, {"version": 1, "docs": []})
    docs = idx.get("docs") if isinstance(idx, dict) else []
    if isinstance(docs, list):
        for doc in docs:
            if isinstance(doc, dict):
                upsert_source(layout.index_db_path, doc)
                src_count += 1

    return {"transactionsIndexed": tx_count, "correctionsIndexed": evt_count, "sourcesIndexed": src_count, "dbPath": str(layout.index_db_path)}


def index_stats(layout: Layout) -> dict[str, Any]:
    ensure_index_schema(layout.index_db_path)
    with _session(layout.index_db_path) as conn:
        tx = int(conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
        tx_live = int(conn.execute("SELECT COUNT(*) FROM transactions WHERE is_deleted = 0").fetchone()[0])
        corr = int(conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0])
        src = int(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
        schema_v = conn.execute("SELECT value FROM meta WHERE key='index_schema_version'").fetchone()
    return {
        "dbPath": str(layout.index_db_path),
        "indexSchemaVersion": int(schema_v[0]) if schema_v else None,
        "transactions": tx,
        "transactionsLive": tx_live,
        "corrections": corr,
        "sources": src,
    }


def has_source_hash(layout: Layout, *, doc_id: str, source_hash: str) -> bool:
    ensure_index_schema(layout.index_db_path)
    with _session(layout.index_db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM transactions WHERE source_doc_id = ? AND source_hash = ? LIMIT 1",
            (doc_id, source_hash),
        ).fetchone()
    return row is not None


def recent_transactions(layout: Layout, *, limit: int, include_deleted: bool = False) -> list[dict[str, Any]]:
    ensure_index_schema(layout.index_db_path)
    where = "" if include_deleted else "WHERE is_deleted = 0"
    with _session(layout.index_db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT raw_json
            FROM transactions
            {where}
            ORDER BY COALESCE(occurred_at, ''), COALESCE(updated_at, '')
            DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            obj = json.loads(r["raw_json"])
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out
