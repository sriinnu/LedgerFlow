from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ledgerflow.extraction import MissingDependencyError, extract_text, ocr_capabilities


class TestExtraction(unittest.TestCase):
    def test_extract_text_plain_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sample.txt"
            p.write_text("hello world", encoding="utf-8")
            text, meta = extract_text(p)
            self.assertEqual(text, "hello world")
            self.assertEqual(meta["method"], "text")

    def test_ocr_capabilities_shape(self) -> None:
        caps = ocr_capabilities()
        self.assertIn("image_ocr_available", caps)
        self.assertIn("pdf_text_available", caps)
        self.assertIn("tesseract_cli", caps)

    def test_image_ocr_fallback_tesseract_cli(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sample.png"
            p.write_bytes(b"not-an-image")

            with patch("ledgerflow.extraction._import_pytesseract", side_effect=ModuleNotFoundError()):
                with patch("ledgerflow.extraction.shutil.which", return_value="/usr/bin/tesseract"):
                    class Proc:
                        returncode = 0
                        stdout = "ocr text"
                        stderr = ""

                    with patch("ledgerflow.extraction.subprocess.run", return_value=Proc()):
                        text, meta = extract_text(p)
                        self.assertEqual(text, "ocr text")
                        self.assertEqual(meta["method"], "tesseract_cli")

    def test_image_ocr_missing_deps(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sample.png"
            p.write_bytes(b"not-an-image")
            with patch("ledgerflow.extraction._import_pytesseract", side_effect=ModuleNotFoundError()):
                with patch("ledgerflow.extraction.shutil.which", return_value=None):
                    with self.assertRaises(MissingDependencyError):
                        extract_text(p)

