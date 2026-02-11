from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ledgerflow.extraction import MissingDependencyError, extract_text, ocr_capabilities


class TestExtraction(unittest.TestCase):
    @staticmethod
    def _write_tiny_png(path: Path) -> None:
        # 1x1 px transparent PNG.
        raw = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO3Zf9sAAAAASUVORK5CYII=")
        path.write_bytes(raw)

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
            self._write_tiny_png(p)

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
            self._write_tiny_png(p)
            with patch("ledgerflow.extraction._import_pytesseract", side_effect=ModuleNotFoundError()):
                with patch("ledgerflow.extraction.shutil.which", return_value=None):
                    with patch("ledgerflow.extraction._openai_vision_available", return_value=False):
                        with self.assertRaises(MissingDependencyError):
                            extract_text(p, image_provider="auto")
