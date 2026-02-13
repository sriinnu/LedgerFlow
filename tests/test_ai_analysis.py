from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledgerflow.ai_analysis import analyze_spending
from ledgerflow.bootstrap import init_data_layout
from ledgerflow.ids import new_id
from ledgerflow.layout import layout_for
from ledgerflow.storage import append_jsonl


def _tx(*, occurred_at: str, amount: str, merchant: str, category_id: str = "groceries", source_type: str = "bank_csv") -> dict:
    conf = 1.0 if category_id != "uncategorized" else 0.0
    tags = ["cash"] if source_type == "manual" else []
    return {
        "txId": new_id("tx"),
        "source": {"docId": new_id("doc"), "sourceType": source_type, "sourceHash": f"sha256:{new_id('h')}", "lineRef": "test:1"},
        "postedAt": occurred_at,
        "occurredAt": occurred_at,
        "amount": {"value": amount, "currency": "USD"},
        "direction": "debit" if amount.startswith("-") else "credit",
        "merchant": merchant,
        "description": merchant,
        "category": {"id": category_id, "confidence": conf, "reason": "test"},
        "tags": tags,
        "confidence": {"extraction": 1.0, "normalization": 1.0, "categorization": conf},
        "links": {"receiptDocId": None, "billDocId": None},
        "createdAt": "2026-02-10T00:00:00Z",
    }


class TestAiAnalysis(unittest.TestCase):
    def test_analyze_spending_heuristic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)

            append_jsonl(layout.transactions_path, _tx(occurred_at="2025-12-05", amount="-100.00", merchant="Grocer", category_id="groceries"))
            append_jsonl(layout.transactions_path, _tx(occurred_at="2026-01-05", amount="-120.00", merchant="Grocer", category_id="groceries"))
            append_jsonl(layout.transactions_path, _tx(occurred_at="2026-02-05", amount="-240.00", merchant="Grocer", category_id="groceries"))
            append_jsonl(layout.transactions_path, _tx(occurred_at="2026-02-06", amount="-80.00", merchant="ATM CASH", category_id="uncategorized", source_type="manual"))
            append_jsonl(layout.transactions_path, _tx(occurred_at="2026-02-01", amount="1200.00", merchant="Payroll", category_id="income"))

            out = analyze_spending(layout, month="2026-02", provider="heuristic", lookback_months=3)
            self.assertEqual(out["providerUsed"], "heuristic")
            self.assertEqual(out["month"], "2026-02")
            self.assertIn("narrative", out)
            self.assertGreaterEqual(len(out.get("insights") or []), 1)
            self.assertEqual(len((out.get("datasets") or {}).get("monthlySpendTrend") or []), 3)
            self.assertEqual(len((out.get("datasets") or {}).get("spendForecast") or []), 3)
            self.assertIn("totalSpend", out.get("quality") or {})

    def test_invalid_month(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)
            with self.assertRaises(ValueError):
                analyze_spending(layout, month="2026-2", provider="heuristic")
