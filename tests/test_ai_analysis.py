from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ledgerflow.ai_analysis import analyze_spending
from ledgerflow.bootstrap import init_data_layout
from ledgerflow.ids import new_id
from ledgerflow.ledger import load_ledger as load_ledger_base
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


def _seed_transactions(layout) -> None:
    append_jsonl(layout.transactions_path, _tx(occurred_at="2025-12-05", amount="-100.00", merchant="Grocer", category_id="groceries"))
    append_jsonl(layout.transactions_path, _tx(occurred_at="2026-01-05", amount="-120.00", merchant="Grocer", category_id="groceries"))
    append_jsonl(layout.transactions_path, _tx(occurred_at="2026-02-05", amount="-240.00", merchant="Grocer", category_id="groceries"))
    append_jsonl(layout.transactions_path, _tx(occurred_at="2026-02-06", amount="-80.00", merchant="ATM CASH", category_id="uncategorized", source_type="manual"))
    append_jsonl(layout.transactions_path, _tx(occurred_at="2026-02-01", amount="1200.00", merchant="Payroll", category_id="income"))


class TestAiAnalysis(unittest.TestCase):
    def test_analyze_spending_heuristic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)
            _seed_transactions(layout)

            out = analyze_spending(layout, month="2026-02", provider="heuristic", lookback_months=3)
            self.assertEqual(out["providerUsed"], "heuristic")
            self.assertEqual(out["month"], "2026-02")
            self.assertIn("narrative", out)
            self.assertGreaterEqual(len(out.get("insights") or []), 1)
            self.assertEqual(len((out.get("datasets") or {}).get("monthlySpendTrend") or []), 3)
            self.assertEqual(len((out.get("datasets") or {}).get("spendForecast") or []), 3)
            self.assertIn("totalSpend", out.get("quality") or {})
            self.assertGreaterEqual(len(out.get("recommendations") or []), 1)
            self.assertIn("confidence", out)
            self.assertIn("explainability", out)
            forecast = (out.get("datasets") or {}).get("spendForecast") or []
            self.assertIn("projectedSpendLower", forecast[0])
            self.assertIn("projectedSpendUpper", forecast[0])
            self.assertIn("confidence", forecast[0])

    def test_invalid_month(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)
            with self.assertRaises(ValueError):
                analyze_spending(layout, month="2026-2", provider="heuristic")

    def test_analyze_spending_loads_ledger_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)
            _seed_transactions(layout)

            with patch("ledgerflow.ai_analysis.load_ledger", wraps=load_ledger_base) as load_mock:
                analyze_spending(layout, month="2026-02", provider="heuristic", lookback_months=3)

            self.assertEqual(load_mock.call_count, 1)
            self.assertFalse(load_mock.call_args.kwargs.get("include_deleted", True))

    def test_auto_provider_falls_back_with_combined_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)
            _seed_transactions(layout)

            with patch("ledgerflow.ai_analysis._try_llm", side_effect=[(None, "ollama offline"), (None, "openai unavailable")]) as try_mock:
                out = analyze_spending(layout, month="2026-02", provider="auto", lookback_months=3)

            self.assertEqual(out["providerRequested"], "auto")
            self.assertEqual(out["providerUsed"], "heuristic")
            self.assertIn("ollama: ollama offline", out.get("llmError") or "")
            self.assertIn("openai: openai unavailable", out.get("llmError") or "")
            self.assertEqual(try_mock.call_count, 2)
            self.assertEqual(try_mock.call_args_list[0].args[0], "ollama")
            self.assertEqual(try_mock.call_args_list[1].args[0], "openai")

    def test_ollama_provider_success_branch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)
            _seed_transactions(layout)

            with patch("ledgerflow.ai_analysis._try_llm", return_value=("ollama narrative", None)) as try_mock:
                out = analyze_spending(layout, month="2026-02", provider="ollama", model="llama3:test", lookback_months=3)

            self.assertEqual(out["providerRequested"], "ollama")
            self.assertEqual(out["providerUsed"], "ollama")
            self.assertEqual(out["narrative"], "ollama narrative")
            self.assertIsNone(out["llmError"])
            self.assertEqual(try_mock.call_count, 1)
            self.assertEqual(try_mock.call_args.args[0], "ollama")
            self.assertEqual(try_mock.call_args.args[2], "llama3:test")

    def test_openai_provider_without_key_uses_heuristic_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)
            _seed_transactions(layout)

            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
                out = analyze_spending(layout, month="2026-02", provider="openai", lookback_months=3)

            self.assertEqual(out["providerRequested"], "openai")
            self.assertEqual(out["providerUsed"], "heuristic")
            self.assertEqual(out["llmError"], "OPENAI_API_KEY not set")
            self.assertIn("For 2026-02", out["narrative"])

    def test_openai_provider_with_key_uses_openai_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)
            _seed_transactions(layout)

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                with patch("ledgerflow.ai_analysis._openai_generate", return_value="openai narrative") as openai_mock:
                    out = analyze_spending(layout, month="2026-02", provider="openai", lookback_months=3)

            self.assertEqual(out["providerRequested"], "openai")
            self.assertEqual(out["providerUsed"], "openai")
            self.assertEqual(out["narrative"], "openai narrative")
            self.assertIsNone(out["llmError"])
            self.assertEqual(openai_mock.call_count, 1)
            self.assertEqual(openai_mock.call_args.kwargs.get("model"), "gpt-4.1-mini")

    def test_confidence_level_and_reasons_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)
            _seed_transactions(layout)

            out = analyze_spending(layout, month="2026-02", provider="heuristic", lookback_months=3)
            confidence = out.get("confidence") or {}
            self.assertIn(confidence.get("level"), {"low", "medium", "high"})
            self.assertTrue(isinstance(confidence.get("reasons"), list))
