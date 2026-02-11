from __future__ import annotations

import unittest

from ledgerflow.parsing import parse_bill_text, parse_receipt_text


class TestParsing(unittest.TestCase):
    def test_receipt_parser_metadata(self) -> None:
        parsed = parse_receipt_text("FARMERS MARKET\n2026-02-10\nTOTAL $12.30\nVAT 10% 1.23\n", default_currency="USD")
        self.assertEqual(parsed["type"], "receipt")
        self.assertIn("parser", parsed)
        self.assertIn("template", parsed["parser"])
        self.assertIn("confidenceBreakdown", parsed)
        self.assertIsInstance(parsed.get("missingFields"), list)
        self.assertIn("needsReview", parsed)
        self.assertGreaterEqual(parsed.get("confidence", 0.0), 0.5)

    def test_bill_parser_metadata(self) -> None:
        parsed = parse_bill_text(
            "UTILITY CO\nInvoice Number: INV-1001\nDue Date: 2026-02-28\nAmount Due $88.40\n",
            default_currency="USD",
        )
        self.assertEqual(parsed["type"], "bill")
        self.assertIn("parser", parsed)
        self.assertIn("template", parsed["parser"])
        self.assertIn("confidenceBreakdown", parsed)
        self.assertIsInstance(parsed.get("missingFields"), list)
        self.assertIn("needsReview", parsed)
        self.assertGreaterEqual(parsed.get("confidence", 0.0), 0.4)
