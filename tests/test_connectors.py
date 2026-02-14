from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ledgerflow.bootstrap import init_data_layout
from ledgerflow.connectors import import_connector_path, list_connectors, normalize_connector_payload
from ledgerflow.layout import layout_for
from ledgerflow.ledger import load_ledger


class TestConnectors(unittest.TestCase):
    def test_list_connectors_contains_plaid(self) -> None:
        ids = {x.get("id") for x in list_connectors()}
        self.assertIn("plaid", ids)
        self.assertIn("wise", ids)

    def test_normalize_plaid_payload(self) -> None:
        payload = {
            "transactions": [
                {
                    "date": "2026-02-10",
                    "name": "Coffee Shop",
                    "merchant_name": "Coffee Shop",
                    "amount": 5.25,
                    "iso_currency_code": "USD",
                }
            ]
        }
        out = normalize_connector_payload("plaid", payload, default_currency="USD")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["date"], "2026-02-10")
        self.assertEqual(out[0]["amount"], "-5.25")

    def test_import_connector_path_commit_and_dedup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=False)

            path = Path(td) / "plaid.json"
            path.write_text(
                json.dumps(
                    {
                        "transactions": [
                            {
                                "date": "2026-02-10",
                                "name": "Coffee Shop",
                                "merchant_name": "Coffee Shop",
                                "amount": 5.25,
                                "iso_currency_code": "USD",
                            },
                            {
                                "date": "2026-02-11",
                                "name": "Payroll",
                                "amount": -1000,
                                "iso_currency_code": "USD",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            c1 = import_connector_path(
                layout,
                connector="plaid",
                path=path,
                commit=True,
                copy_into_sources=False,
                default_currency="USD",
                sample=5,
                max_rows=None,
            )
            self.assertEqual(c1["imported"], 2)

            c2 = import_connector_path(
                layout,
                connector="plaid",
                path=path,
                commit=True,
                copy_into_sources=False,
                default_currency="USD",
                sample=5,
                max_rows=None,
            )
            self.assertEqual(c2["imported"], 0)
            self.assertEqual(c2["skipped"], 2)

            txs = load_ledger(layout).transactions
            self.assertEqual(len(txs), 2)
            self.assertTrue(all(((t.get("source") or {}).get("sourceType") == "connector_plaid") for t in txs))


if __name__ == "__main__":
    unittest.main()
