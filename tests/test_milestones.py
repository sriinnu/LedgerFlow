from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ledgerflow.alerts import run_alerts
from ledgerflow.bootstrap import init_data_layout
from ledgerflow.building import build_daily_monthly_caches
from ledgerflow.charts import write_category_breakdown_month, write_merchant_top_month, write_series
from ledgerflow.documents import import_and_parse_receipt
from ledgerflow.ids import new_id
from ledgerflow.layout import layout_for
from ledgerflow.ledger import load_ledger
from ledgerflow.linking import link_receipts_to_bank
from ledgerflow.reporting import write_daily_report, write_monthly_report
from ledgerflow.storage import append_jsonl, read_json, write_json


class TestMilestones(unittest.TestCase):
    def test_build_reports_charts_alerts_and_linking(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)

            # Seed a bank tx.
            doc_id = new_id("doc")
            tx_id = new_id("tx")
            bank_tx = {
                "txId": tx_id,
                "source": {"docId": doc_id, "sourceType": "bank_csv", "sourceHash": "sha256:test", "lineRef": "csv:row:1"},
                "postedAt": "2026-02-10",
                "occurredAt": "2026-02-10",
                "amount": {"value": "-12.30", "currency": "USD"},
                "direction": "debit",
                "merchant": "",
                "description": "FARMERS MARKET",
                "category": {"id": "groceries", "confidence": 0.5, "reason": "test"},
                "tags": [],
                "confidence": {"extraction": 1.0, "normalization": 1.0, "categorization": 0.5},
                "links": {"receiptDocId": None, "billDocId": None},
                "createdAt": "2026-02-10T00:00:00Z",
            }
            append_jsonl(layout.transactions_path, bank_tx)

            # Build derived caches.
            summary = build_daily_monthly_caches(layout)
            self.assertIn("2026-02-10", summary["days"])
            self.assertIn("2026-02", summary["months"])

            # Daily/monthly reports.
            daily_paths = write_daily_report(layout, date="2026-02-10")
            self.assertTrue(Path(daily_paths["md"]).exists())
            self.assertTrue(Path(daily_paths["json"]).exists())

            monthly_paths = write_monthly_report(layout, month="2026-02")
            self.assertTrue(Path(monthly_paths["md"]).exists())
            self.assertTrue(Path(monthly_paths["json"]).exists())

            # Chart datasets.
            series_path = write_series(layout, from_date="2026-02-10", to_date="2026-02-10")
            self.assertTrue(Path(series_path).exists())
            self.assertTrue(Path(write_category_breakdown_month(layout, month="2026-02")).exists())
            self.assertTrue(Path(write_merchant_top_month(layout, month="2026-02")).exists())

            # Alerts (budget exceeded).
            write_json(
                layout.alert_rules_path,
                {
                    "currency": "USD",
                    "rules": [
                        {"id": "groceries_monthly", "type": "category_budget", "categoryId": "groceries", "period": "month", "limit": 10}
                    ],
                },
            )
            r1 = run_alerts(layout, at_date="2026-02-10", commit=True)
            self.assertEqual(r1["eventCount"], 1)
            r2 = run_alerts(layout, at_date="2026-02-10", commit=True)
            self.assertEqual(r2["eventCount"], 0)

            # Import receipt from plain text and link it.
            receipt_txt = Path(td) / "receipt.txt"
            receipt_txt.write_text("FARMERS MARKET\n2026-02-10\nTOTAL $12.30\n", encoding="utf-8")
            rec = import_and_parse_receipt(layout, receipt_txt, copy_into_sources=False, default_currency="USD")
            rid = rec["doc"]["docId"]

            link_res = link_receipts_to_bank(layout, commit=True)
            self.assertGreaterEqual(link_res["created"], 1)

            view = load_ledger(layout)
            txs = [t for t in view.transactions if t.get("txId") == tx_id]
            self.assertEqual(len(txs), 1)
            self.assertEqual((txs[0].get("links") or {}).get("receiptDocId"), rid)

