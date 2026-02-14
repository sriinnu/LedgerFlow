from __future__ import annotations

import unittest

from ledgerflow.cli import build_parser


class TestCliSurface(unittest.TestCase):
    def test_top_level_commands_include_ocr(self) -> None:
        parser = build_parser()
        subactions = [a for a in parser._actions if getattr(a, "choices", None)]
        choices = set()
        for a in subactions:
            choices.update(a.choices.keys())
        self.assertIn("ocr", choices)
        self.assertIn("serve", choices)
        self.assertIn("report", choices)
        self.assertIn("review", choices)
        self.assertIn("ai", choices)
        self.assertIn("automation", choices)
        self.assertIn("backup", choices)
        self.assertIn("ops", choices)
        self.assertIn("connectors", choices)

    def test_ocr_extract_flags(self) -> None:
        parser = build_parser()
        ns = parser.parse_args(
            [
                "ocr",
                "extract",
                "sample.png",
                "--image-provider",
                "tesseract",
                "--no-preprocess",
            ]
        )
        self.assertEqual(ns.path, "sample.png")
        self.assertEqual(ns.image_provider, "tesseract")
        self.assertTrue(ns.no_preprocess)

    def test_import_receipt_ocr_flags(self) -> None:
        parser = build_parser()
        ns = parser.parse_args(
            [
                "import",
                "receipt",
                "receipt.jpg",
                "--image-provider",
                "openai",
                "--no-preprocess",
            ]
        )
        self.assertEqual(ns.path, "receipt.jpg")
        self.assertEqual(ns.image_provider, "openai")
        self.assertTrue(ns.no_preprocess)

    def test_ai_analyze_flags(self) -> None:
        parser = build_parser()
        ns = parser.parse_args(
            [
                "ai",
                "analyze",
                "--month",
                "2026-02",
                "--provider",
                "ollama",
                "--model",
                "llama3.1:8b",
                "--lookback-months",
                "9",
                "--json",
            ]
        )
        self.assertEqual(ns.month, "2026-02")
        self.assertEqual(ns.provider, "ollama")
        self.assertEqual(ns.model, "llama3.1:8b")
        self.assertEqual(ns.lookback_months, 9)
        self.assertTrue(ns.json)

    def test_import_bank_json_flags(self) -> None:
        parser = build_parser()
        ns = parser.parse_args(
            [
                "import",
                "bank-json",
                "statement.json",
                "--currency",
                "EUR",
                "--commit",
                "--sample",
                "3",
                "--mapping-file",
                "mapping.json",
            ]
        )
        self.assertEqual(ns.path, "statement.json")
        self.assertEqual(ns.currency, "EUR")
        self.assertTrue(ns.commit)
        self.assertEqual(ns.sample, 3)
        self.assertEqual(ns.mapping_file, "mapping.json")

    def test_automation_enqueue_flags(self) -> None:
        parser = build_parser()
        ns = parser.parse_args(
            [
                "automation",
                "enqueue",
                "--task-type",
                "ai.analyze",
                "--payload-json",
                '{"month":"2026-02"}',
                "--max-retries",
                "4",
            ]
        )
        self.assertEqual(ns.task_type, "ai.analyze")
        self.assertEqual(ns.payload_json, '{"month":"2026-02"}')
        self.assertEqual(ns.max_retries, 4)

    def test_automation_dispatch_flags(self) -> None:
        parser = build_parser()
        ns = parser.parse_args(
            [
                "automation",
                "dispatch",
                "--skip-due",
                "--at",
                "2026-02-10T10:00:00Z",
                "--worker-id",
                "disp",
                "--max-tasks",
                "12",
            ]
        )
        self.assertTrue(ns.skip_due)
        self.assertEqual(ns.at, "2026-02-10T10:00:00Z")
        self.assertEqual(ns.worker_id, "disp")
        self.assertEqual(ns.max_tasks, 12)

    def test_automation_stats_and_dead_letters_flags(self) -> None:
        parser = build_parser()
        ns1 = parser.parse_args(["automation", "stats"])
        self.assertEqual(ns1.automation_cmd, "stats")

        ns2 = parser.parse_args(["automation", "dead-letters", "--limit", "15"])
        self.assertEqual(ns2.automation_cmd, "dead-letters")
        self.assertEqual(ns2.limit, 15)

    def test_backup_and_ops_flags(self) -> None:
        parser = build_parser()
        b1 = parser.parse_args(["backup", "create", "--out", "backup.tar.gz", "--no-inbox"])
        self.assertEqual(b1.backup_cmd, "create")
        self.assertEqual(b1.out, "backup.tar.gz")
        self.assertTrue(b1.no_inbox)

        b2 = parser.parse_args(["backup", "restore", "--archive", "backup.tar.gz", "--target-dir", "restore", "--force"])
        self.assertEqual(b2.backup_cmd, "restore")
        self.assertEqual(b2.archive, "backup.tar.gz")
        self.assertEqual(b2.target_dir, "restore")
        self.assertTrue(b2.force)

        o1 = parser.parse_args(["ops", "metrics"])
        self.assertEqual(o1.ops_cmd, "metrics")

    def test_connectors_and_import_connector_flags(self) -> None:
        parser = build_parser()
        c1 = parser.parse_args(["connectors", "list"])
        self.assertEqual(c1.connectors_cmd, "list")

        c2 = parser.parse_args(
            [
                "import",
                "connector",
                "--connector",
                "plaid",
                "plaid.json",
                "--commit",
                "--sample",
                "7",
            ]
        )
        self.assertEqual(c2.connector, "plaid")
        self.assertEqual(c2.path, "plaid.json")
        self.assertTrue(c2.commit)
        self.assertEqual(c2.sample, 7)

    def test_alerts_deliver_and_outbox_flags(self) -> None:
        parser = build_parser()

        d = parser.parse_args(
            [
                "alerts",
                "deliver",
                "--limit",
                "25",
                "--channel",
                "local_outbox",
                "--channel",
                "webhook_ops",
                "--dry-run",
            ]
        )
        self.assertEqual(d.alerts_cmd, "deliver")
        self.assertEqual(d.limit, 25)
        self.assertEqual(d.channel, ["local_outbox", "webhook_ops"])
        self.assertTrue(d.dry_run)

        o = parser.parse_args(["alerts", "outbox", "--limit", "15"])
        self.assertEqual(o.alerts_cmd, "outbox")
        self.assertEqual(o.limit, 15)
