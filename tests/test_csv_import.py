from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledgerflow.csv_import import csv_row_to_tx, infer_mapping, parse_amount_text, read_csv_rows


class TestCsvImport(unittest.TestCase):
    def test_parse_amount_text(self) -> None:
        self.assertEqual(parse_amount_text("12.34"), parse_amount_text("12.34"))
        self.assertEqual(str(parse_amount_text("(12.34)")), "-12.34")
        self.assertEqual(str(parse_amount_text("12.34-")), "-12.34")

    def test_infer_mapping_and_row_to_tx(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bank.csv"
            p.write_text(
                "Date,Description,Amount,Currency\n"
                "2026-02-10,FARMERS MARKET,-12.30,USD\n"
                "2026-02-11,SALARY,1000.00,USD\n",
                encoding="utf-8",
            )
            headers, rows = read_csv_rows(p)
            mapping = infer_mapping(headers)

            tx = csv_row_to_tx(
                doc_id="doc_test",
                row_index=1,
                row=rows[0],
                mapping=mapping,
                default_currency="USD",
                date_format=None,
                day_first=False,
            )
            self.assertEqual(tx["occurredAt"], "2026-02-10")
            self.assertEqual(tx["amount"]["currency"], "USD")
            self.assertEqual(tx["direction"], "debit")

