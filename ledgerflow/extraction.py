from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import LedgerFlowError


class MissingDependencyError(LedgerFlowError):
    pass


def ocr_capabilities() -> dict[str, Any]:
    caps = {
        "pdfplumber": False,
        "pypdf": False,
        "pytesseract": False,
        "tesseract_cli": bool(shutil.which("tesseract")),
    }
    try:
        import pdfplumber  # type: ignore  # noqa: F401

        caps["pdfplumber"] = True
    except Exception:
        pass
    try:
        from pypdf import PdfReader  # type: ignore  # noqa: F401

        caps["pypdf"] = True
    except Exception:
        pass
    try:
        _import_pytesseract()
        caps["pytesseract"] = True
    except Exception:
        pass
    caps["image_ocr_available"] = bool(caps["pytesseract"] or caps["tesseract_cli"])
    caps["pdf_text_available"] = bool(caps["pdfplumber"] or caps["pypdf"])
    return caps


def extract_text(path: str | Path) -> tuple[str, dict[str, Any]]:
    p = Path(path)
    ext = p.suffix.lower()

    if ext in (".txt", ".text"):
        return p.read_text(encoding="utf-8", errors="replace"), {"method": "text"}

    if ext == ".pdf":
        return _extract_text_pdf(p)

    if ext in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"):
        return _extract_text_image(p)

    raise LedgerFlowError(f"Unsupported file type for text extraction: {ext}")


def _extract_text_pdf(p: Path) -> tuple[str, dict[str, Any]]:
    # Try pdfplumber first (best quality for text extraction).
    try:
        import pdfplumber  # type: ignore

        parts = []
        with pdfplumber.open(str(p)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n\n".join(parts).strip(), {"method": "pdfplumber"}
    except ModuleNotFoundError:
        pass
    except Exception as e:
        raise LedgerFlowError(f"Failed to extract PDF text via pdfplumber: {e}") from e

    # Fallback: pypdf
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(p))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n\n".join(parts).strip(), {"method": "pypdf"}
    except ModuleNotFoundError as e:
        raise MissingDependencyError(
            "PDF text extraction requires an optional dependency. Install one of: pdfplumber, pypdf."
        ) from e
    except Exception as e:
        raise LedgerFlowError(f"Failed to extract PDF text via pypdf: {e}") from e


def _extract_text_image(p: Path) -> tuple[str, dict[str, Any]]:
    # OCR path 1: pytesseract + PIL.
    try:
        pytesseract = _import_pytesseract()
        from PIL import Image

        img = Image.open(str(p))
        text = pytesseract.image_to_string(img)
        return text.strip(), {"method": "pytesseract"}
    except ModuleNotFoundError as e:
        pass
    except Exception as e:
        raise LedgerFlowError(f"Failed to OCR image via pytesseract: {e}") from e

    # OCR path 2: fallback to `tesseract <image> stdout` if binary exists.
    tesseract = shutil.which("tesseract")
    if tesseract:
        proc = subprocess.run(
            [tesseract, str(p), "stdout"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            raise LedgerFlowError(f"tesseract failed: {stderr or f'exit {proc.returncode}'}")
        return (proc.stdout or "").strip(), {"method": "tesseract_cli"}

    raise MissingDependencyError(
        "Image OCR requires pytesseract (with tesseract) or a system tesseract binary on PATH."
    )


def _import_pytesseract() -> Any:
    try:
        import pytesseract  # type: ignore

        return pytesseract
    except Exception as e:
        raise ModuleNotFoundError("pytesseract not available") from e
