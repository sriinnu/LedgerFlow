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

