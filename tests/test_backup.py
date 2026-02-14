from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledgerflow.backup import create_backup, restore_backup
from ledgerflow.bootstrap import init_data_layout
from ledgerflow.layout import layout_for
from ledgerflow.storage import append_jsonl


class TestBackup(unittest.TestCase):
    def test_create_and_restore_backup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            layout = layout_for(data_dir)
            init_data_layout(layout, write_defaults=True)

            append_jsonl(layout.transactions_path, {"txId": "tx_1", "occurredAt": "2026-02-10", "amount": {"value": "-1", "currency": "USD"}})
            (layout.inbox_dir / "sample.txt").write_text("hello", encoding="utf-8")

            archive = create_backup(layout)
            self.assertTrue(Path(archive["archivePath"]).exists())
            self.assertGreater(archive["fileCount"], 0)

            target = Path(td) / "restored"
            res = restore_backup(archive["archivePath"], target_dir=target)
            self.assertTrue((target / "ledger" / "transactions.jsonl").exists())
            self.assertGreaterEqual(res["extractedEntries"], 1)

    def test_restore_requires_force_for_non_empty_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            layout = layout_for(data_dir)
            init_data_layout(layout, write_defaults=True)

            archive = create_backup(layout)
            target = Path(td) / "restore_non_empty"
            target.mkdir(parents=True, exist_ok=True)
            (target / "keep.txt").write_text("x", encoding="utf-8")

            with self.assertRaises(ValueError):
                restore_backup(archive["archivePath"], target_dir=target, force=False)

            out = restore_backup(archive["archivePath"], target_dir=target, force=True)
            self.assertGreaterEqual(out["extractedEntries"], 1)

    def test_backup_excludes_inbox_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            layout = layout_for(data_dir)
            init_data_layout(layout, write_defaults=True)
            (layout.inbox_dir / "secret.txt").write_text("top-secret", encoding="utf-8")

            archive = create_backup(layout, include_inbox=False)
            target = Path(td) / "restored-no-inbox"
            restore_backup(archive["archivePath"], target_dir=target)
            self.assertFalse((target / "inbox" / "secret.txt").exists())


if __name__ == "__main__":
    unittest.main()
