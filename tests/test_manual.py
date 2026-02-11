from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ledgerflow.layout import layout_for
from ledgerflow.manual import ManualEntry, manual_entry_to_tx
from ledgerflow.storage import append_jsonl, read_json


class TestManual(unittest.TestCase):
    def test_manual_add_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            entry = ManualEntry(
                occurred_at="2026-02-10",
                amount_value=Decimal("-12.30"),
                currency="USD",
                merchant="Farmers Market",
                description="cash vegetables",
                category_hint="groceries",
                tags=["cash"],
            )
            tx = manual_entry_to_tx(entry)
            append_jsonl(layout.transactions_path, tx)

            lines = layout.transactions_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            obj = json.loads(lines[0])
            self.assertEqual(obj["merchant"], "Farmers Market")
            self.assertEqual(obj["category"]["id"], "groceries")

