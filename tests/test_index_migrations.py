from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledgerflow.bootstrap import init_data_layout
from ledgerflow.ids import new_id
from ledgerflow.index_db import has_source_hash, index_stats, recent_transactions, rebuild_index
from ledgerflow.layout import layout_for
from ledgerflow.migrations import APP_SCHEMA_VERSION, migrate_to_latest, status as migration_status
from ledgerflow.storage import append_jsonl


class TestIndexAndMigrations(unittest.TestCase):
    def test_index_incremental_and_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)

            doc_id = new_id("doc")
            tx_id = new_id("tx")
            tx = {
                "txId": tx_id,
                "source": {"docId": doc_id, "sourceType": "bank_csv", "sourceHash": "sha256:abc", "lineRef": "csv:row:1"},
                "postedAt": "2026-02-10",
                "occurredAt": "2026-02-10",
                "amount": {"value": "-10.00", "currency": "USD"},
                "direction": "debit",
                "merchant": "A",
                "description": "A",
                "category": {"id": "uncategorized", "confidence": 0.0, "reason": "test"},
                "tags": [],
                "confidence": {"extraction": 1.0, "normalization": 1.0, "categorization": 0.0},
                "links": {"receiptDocId": None, "billDocId": None},
                "createdAt": "2026-02-10T00:00:00Z",
            }
            append_jsonl(layout.transactions_path, tx)

            self.assertTrue(has_source_hash(layout, doc_id=doc_id, source_hash="sha256:abc"))

            evt = {
                "eventId": new_id("evt"),
                "txId": tx_id,
                "type": "patch",
                "patch": {"merchant": "B"},
                "reason": "test",
                "at": "2026-02-10T00:01:00Z",
            }
            append_jsonl(layout.corrections_path, evt)

            items = recent_transactions(layout, limit=10)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["merchant"], "B")

            stats_before = index_stats(layout)
            self.assertGreaterEqual(stats_before["transactions"], 1)
            rebuild = rebuild_index(layout)
            self.assertGreaterEqual(rebuild["transactionsIndexed"], 1)

    def test_migration_status_and_up(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)
            st = migration_status(layout)
            self.assertIn("currentVersion", st)
            out = migrate_to_latest(layout)
            self.assertEqual(out["toVersion"], APP_SCHEMA_VERSION)
            st2 = migration_status(layout)
            self.assertEqual(st2["currentVersion"], APP_SCHEMA_VERSION)

