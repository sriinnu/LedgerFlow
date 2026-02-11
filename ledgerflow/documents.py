from __future__ import annotations

from pathlib import Path
from typing import Any

from .extraction import extract_text
from .layout import Layout
from .parsing import parse_bill_text, parse_receipt_text
from .sources import register_file
from .storage import write_json
from .timeutil import utc_now_iso


def _doc_dir(layout: Layout, doc_id: str) -> Path:
    return layout.sources_dir / doc_id


def import_and_parse_receipt(
    layout: Layout,
    path: str | Path,
    *,
    copy_into_sources: bool = False,
    default_currency: str = "USD",
) -> dict[str, Any]:
    doc = register_file(
        layout.sources_dir,
        layout.sources_index_path,
        path,
        copy_into_sources=copy_into_sources,
        source_type="receipt",
    )
    doc_id = doc["docId"]
    doc_dir = _doc_dir(layout, doc_id)

    text, meta = extract_text(path)
    (doc_dir / "raw.txt").write_text(text, encoding="utf-8")

    parsed = parse_receipt_text(text, default_currency=default_currency)
    parsed["docId"] = doc_id
    parsed["extraction"] = meta
    parsed["parsedAt"] = utc_now_iso()

    write_json(doc_dir / "parse.json", parsed)
    return {"doc": doc, "parse": parsed}


def import_and_parse_bill(
    layout: Layout,
    path: str | Path,
    *,
    copy_into_sources: bool = False,
    default_currency: str = "USD",
) -> dict[str, Any]:
    doc = register_file(
        layout.sources_dir,
        layout.sources_index_path,
        path,
        copy_into_sources=copy_into_sources,
        source_type="bill",
    )
    doc_id = doc["docId"]
    doc_dir = _doc_dir(layout, doc_id)

    text, meta = extract_text(path)
    (doc_dir / "raw.txt").write_text(text, encoding="utf-8")

    parsed = parse_bill_text(text, default_currency=default_currency)
    parsed["docId"] = doc_id
    parsed["extraction"] = meta
    parsed["parsedAt"] = utc_now_iso()

    write_json(doc_dir / "parse.json", parsed)
    return {"doc": doc, "parse": parsed}

