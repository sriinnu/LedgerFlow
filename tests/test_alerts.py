from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledgerflow.alerts import run_alerts
from ledgerflow.bootstrap import init_data_layout
from ledgerflow.ids import new_id
from ledgerflow.layout import layout_for
from ledgerflow.storage import append_jsonl, write_json


def _tx(
    *,
    occurred_at: str,
    amount: str,
    merchant: str,
    source_type: str = "bank_csv",
    category_id: str = "groceries",
    category_conf: float = 1.0,
) -> dict:
    return {
        "txId": new_id("tx"),
        "source": {"docId": new_id("doc"), "sourceType": source_type, "sourceHash": f"sha256:{new_id('h')}", "lineRef": "test:1"},
        "postedAt": occurred_at,
        "occurredAt": occurred_at,
        "amount": {"value": amount, "currency": "USD"},
        "direction": "debit" if amount.startswith("-") else "credit",
        "merchant": merchant,
        "description": merchant,
        "category": {"id": category_id, "confidence": category_conf, "reason": "test"},
        "tags": [],
        "confidence": {"extraction": 1.0, "normalization": 1.0, "categorization": category_conf},
        "links": {"receiptDocId": None, "billDocId": None},
        "createdAt": "2026-02-10T00:00:00Z",
    }


class TestAlertRules(unittest.TestCase):
    def test_merchant_spike(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)

            append_jsonl(layout.transactions_path, _tx(occurred_at="2025-11-05", amount="-20.00", merchant="ACME"))
            append_jsonl(layout.transactions_path, _tx(occurred_at="2025-12-05", amount="-20.00", merchant="ACME"))
            append_jsonl(layout.transactions_path, _tx(occurred_at="2026-01-05", amount="-20.00", merchant="ACME"))
            append_jsonl(layout.transactions_path, _tx(occurred_at="2026-02-05", amount="-120.00", merchant="ACME"))

            write_json(
                layout.alert_rules_path,
                {
                    "currency": "USD",
                    "rules": [
                        {
                            "id": "merchant_spike",
                            "type": "merchant_spike",
                            "period": "month",
                            "lookbackPeriods": 3,
                            "multiplier": 1.5,
                            "minDelta": 20,
                        }
                    ],
                },
            )
            out = run_alerts(layout, at_date="2026-02-10", commit=False)
            self.assertEqual(out["eventCount"], 1)
            self.assertEqual(out["events"][0]["type"], "merchant_spike")

    def test_recurring_changed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)

            append_jsonl(layout.transactions_path, _tx(occurred_at="2025-11-01", amount="-20.00", merchant="StreamCo"))
            append_jsonl(layout.transactions_path, _tx(occurred_at="2025-12-01", amount="-20.00", merchant="StreamCo"))
            append_jsonl(layout.transactions_path, _tx(occurred_at="2026-01-01", amount="-20.00", merchant="StreamCo"))
            append_jsonl(layout.transactions_path, _tx(occurred_at="2026-02-01", amount="-35.00", merchant="StreamCo"))

            write_json(
                layout.alert_rules_path,
                {
                    "currency": "USD",
                    "rules": [
                        {
                            "id": "recurring_changed",
                            "type": "recurring_changed",
                            "minOccurrences": 3,
                            "spacingDays": [25, 35],
                            "minDelta": 5,
                            "minDeltaPct": 5,
                        }
                    ],
                },
            )
            out = run_alerts(layout, at_date="2026-02-10", commit=False)
            self.assertEqual(out["eventCount"], 1)
            self.assertEqual(out["events"][0]["type"], "recurring_changed")

    def test_cash_heavy_day_and_unclassified_spend(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)

            append_jsonl(
                layout.transactions_path,
                _tx(
                    occurred_at="2026-02-10",
                    amount="-200.00",
                    merchant="ATM CASH",
                    source_type="manual",
                    category_id="uncategorized",
                    category_conf=0.0,
                ),
            )
            append_jsonl(
                layout.transactions_path,
                _tx(
                    occurred_at="2026-02-10",
                    amount="-80.00",
                    merchant="Unknown Merchant",
                    source_type="bank_csv",
                    category_id="uncategorized",
                    category_conf=0.1,
                ),
            )

            write_json(
                layout.alert_rules_path,
                {
                    "currency": "USD",
                    "rules": [
                        {"id": "cash_heavy_day", "type": "cash_heavy_day", "limit": 100},
                        {
                            "id": "uncategorized_day",
                            "type": "unclassified_spend",
                            "period": "day",
                            "categoryConfidenceBelow": 0.6,
                            "limit": 50,
                        },
                    ],
                },
            )
            out = run_alerts(layout, at_date="2026-02-10", commit=False)
            self.assertEqual(out["eventCount"], 2)
            types = {evt["type"] for evt in out["events"]}
            self.assertIn("cash_heavy_day", types)
            self.assertIn("unclassified_spend", types)
