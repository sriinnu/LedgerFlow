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
