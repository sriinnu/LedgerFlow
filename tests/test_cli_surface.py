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
