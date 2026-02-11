from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledgerflow.layout import layout_for
from ledgerflow.sources import register_file
from ledgerflow.storage import read_json


class TestSources(unittest.TestCase):
    def test_register_is_idempotent_by_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            layout = layout_for(td_path / "data")
            layout.sources_dir.mkdir(parents=True, exist_ok=True)

            sample = td_path / "sample.txt"
            sample.write_text("hello", encoding="utf-8")

            doc1 = register_file(layout.sources_dir, layout.sources_index_path, sample, copy_into_sources=False)
            doc2 = register_file(layout.sources_dir, layout.sources_index_path, sample, copy_into_sources=False)
            self.assertEqual(doc1["docId"], doc2["docId"])

