from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import tempfile
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
        "openai_vision": False,
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
    caps["openai_vision"] = _openai_vision_available()
    caps["image_ocr_available"] = bool(caps["pytesseract"] or caps["tesseract_cli"])
    caps["pdf_text_available"] = bool(caps["pdfplumber"] or caps["pypdf"])
    return caps


def extract_text(
    path: str | Path,
    *,
    image_provider: str = "auto",
    preprocess: bool = True,
) -> tuple[str, dict[str, Any]]:
    p = Path(path)
    ext = p.suffix.lower()

    if ext in (".txt", ".text"):
        return p.read_text(encoding="utf-8", errors="replace"), {"method": "text"}

    if ext == ".pdf":
        return _extract_text_pdf(p)

    if ext in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"):
        return _extract_text_image(p, image_provider=image_provider, preprocess=preprocess)

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


def _extract_text_image(p: Path, *, image_provider: str = "auto", preprocess: bool = True) -> tuple[str, dict[str, Any]]:
    provider = image_provider.lower().strip()
    if provider not in ("auto", "pytesseract", "tesseract", "openai"):
        raise LedgerFlowError("image_provider must be one of: auto, pytesseract, tesseract, openai")

    attempts: list[str] = []

    def _try(name: str, fn: Any) -> tuple[str, dict[str, Any]] | None:
        try:
            return fn()
        except Exception as e:
            attempts.append(f"{name}:{e}")
            return None

    if provider in ("auto", "pytesseract"):
        out = _try("pytesseract", lambda: _ocr_with_pytesseract(p, preprocess=preprocess))
        if out is not None:
            return out
        if provider == "pytesseract":
            raise LedgerFlowError("; ".join(attempts))

    if provider in ("auto", "tesseract"):
        out = _try("tesseract", lambda: _ocr_with_tesseract_cli(p, preprocess=preprocess))
        if out is not None:
            return out
        if provider == "tesseract":
            raise LedgerFlowError("; ".join(attempts))

    if provider in ("auto", "openai"):
        out = _try("openai", lambda: _ocr_with_openai_vision(p))
        if out is not None:
            return out
        if provider == "openai":
            raise LedgerFlowError("; ".join(attempts))

    raise MissingDependencyError(
        "Image OCR is unavailable. Install pytesseract+tesseract or tesseract CLI, or configure OPENAI_API_KEY with openai."
    )


def _ocr_with_pytesseract(path: Path, *, preprocess: bool) -> tuple[str, dict[str, Any]]:
    pytesseract = _import_pytesseract()
    from PIL import Image

    img = Image.open(str(path))
    variants = _image_variants(img) if preprocess else [("original", img)]

    best_text = ""
    best_variant = "original"
    best_score = -1.0
    for name, variant in variants:
        text = (pytesseract.image_to_string(variant, config="--psm 6") or "").strip()
        score = _ocr_score(text)
        if score > best_score:
            best_text = text
            best_variant = name
            best_score = score

    return best_text, {"method": "pytesseract", "variant": best_variant, "score": round(best_score, 3), "preprocess": preprocess}


def _ocr_with_tesseract_cli(path: Path, *, preprocess: bool) -> tuple[str, dict[str, Any]]:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise MissingDependencyError("tesseract binary not found on PATH")

    from PIL import Image

    img = Image.open(str(path))
    variants = _image_variants(img) if preprocess else [("original", img)]

    best_text = ""
    best_variant = "original"
    best_score = -1.0

    with tempfile.TemporaryDirectory() as td:
        for name, variant in variants:
            in_path = Path(td) / f"{name}.png"
            variant.save(str(in_path), format="PNG")
            proc = subprocess.run(
                [tesseract, str(in_path), "stdout", "--psm", "6"],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                continue
            text = (proc.stdout or "").strip()
            score = _ocr_score(text)
            if score > best_score:
                best_text = text
                best_variant = name
                best_score = score

    if best_score < 0:
        raise LedgerFlowError("tesseract failed on all image variants")

    return best_text, {"method": "tesseract_cli", "variant": best_variant, "score": round(best_score, 3), "preprocess": preprocess}


def _ocr_with_openai_vision(path: Path) -> tuple[str, dict[str, Any]]:
    if not _openai_vision_available():
        raise MissingDependencyError("OpenAI vision OCR is not available (needs OPENAI_API_KEY and openai package).")

    try:
        from openai import OpenAI  # type: ignore
        from PIL import Image
    except Exception as e:
        raise MissingDependencyError("OpenAI OCR requires openai and Pillow packages.") from e

    img = Image.open(str(path)).convert("RGB")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    b64 = base64.b64encode(bio.getvalue()).decode("ascii")

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Extract all readable text from this image. Return only the extracted text."},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{b64}"},
                ],
            }
        ],
        max_output_tokens=2000,
    )
    text = (getattr(resp, "output_text", None) or "").strip()
    return text, {"method": "openai_vision", "model": "gpt-4.1-mini"}


def _ocr_score(text: str) -> float:
    s = text.strip()
    if not s:
        return 0.0
    alnum = sum(1 for ch in s if ch.isalnum())
    spaces = sum(1 for ch in s if ch.isspace())
    return float(alnum + (0.3 * spaces))


def _image_variants(img: Any) -> list[tuple[str, Any]]:
    from PIL import ImageFilter, ImageOps

    gray = ImageOps.grayscale(img)
    auto = ImageOps.autocontrast(gray)
    sharp = auto.filter(ImageFilter.SHARPEN)
    bw = sharp.point(lambda x: 255 if x > 160 else 0).convert("L")
    upscaled = auto.resize((max(1, auto.width * 2), max(1, auto.height * 2)))
    return [("original", img), ("gray", gray), ("auto", auto), ("sharp", sharp), ("bw", bw), ("upscaled", upscaled)]


def _openai_vision_available() -> bool:
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    try:
        from openai import OpenAI  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


def _import_pytesseract() -> Any:
    try:
        import pytesseract  # type: ignore

        return pytesseract
    except Exception as e:
        raise ModuleNotFoundError("pytesseract not available") from e
