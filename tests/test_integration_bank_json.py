from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ledgerflow.bootstrap import init_data_layout
from ledgerflow.integration_bank_json import import_bank_json_path
from ledgerflow.layout import layout_for
from ledgerflow.ledger import load_ledger


class TestIntegrationBankJson(unittest.TestCase):
    def test_bank_json_dry_run_and_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)

            path = Path(td) / "bank.json"
            payload = {
                "transactions": [
                    {
                        "date": "2026-02-10",
                        "amount": -12.3,
                        "currency": "USD",
                        "merchant": "Farmers Market",
                        "description": "Card purchase",
                    },
                    {
                        "date": "2026-02-11",
                        "amount": 1000,
                        "currency": "USD",
                        "merchant": "Employer",
                        "description": "Salary",
                    },
                ]
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            dry = import_bank_json_path(
                layout,
                path,
                commit=False,
                copy_into_sources=False,
                default_currency="USD",
                sample=5,
                max_rows=None,
            )
            self.assertEqual(dry["mode"], "dry-run")
            self.assertEqual(len(dry["sample"]), 2)

            c1 = import_bank_json_path(
                layout,
                path,
                commit=True,
                copy_into_sources=False,
                default_currency="USD",
                sample=5,
                max_rows=None,
            )
            self.assertEqual(c1["imported"], 2)

            c2 = import_bank_json_path(
                layout,
                path,
                commit=True,
                copy_into_sources=False,
                default_currency="USD",
                sample=5,
                max_rows=None,
            )
            self.assertEqual(c2["imported"], 0)
            self.assertEqual(c2["skipped"], 2)

            view = load_ledger(layout)
            self.assertEqual(len(view.transactions), 2)
            self.assertTrue(all(((t.get("source") or {}).get("sourceType") == "bank_json") for t in view.transactions))


if __name__ == "__main__":
    unittest.main()
