from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .hashing import sha256_file
from .ids import new_id
from .storage import ensure_dir, read_json, write_json
from .timeutil import utc_now_iso


def _index_default() -> dict[str, Any]:
    return {"version": 1, "docs": []}


def register_file(
    layout_sources_dir: Path,
    index_path: Path,
    file_path: str | Path,
    *,
    copy_into_sources: bool,
    source_type: str | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = Path(file_path)
    sha = sha256_file(p)

    index = read_json(index_path, _index_default())
    for doc in index.get("docs", []):
        if doc.get("sha256") == sha:
            # If the doc already exists but we now have extra metadata, merge it in.
            changed = False
            if source_type and not doc.get("sourceType"):
                doc["sourceType"] = source_type
                changed = True
            if extra_meta:
                for k, v in extra_meta.items():
                    if k not in doc:
                        doc[k] = v
                        changed = True
            if changed:
                # Update meta.json as well for the canonical doc record.
                doc_dir_existing = layout_sources_dir / str(doc.get("docId"))
                if doc_dir_existing.exists():
                    write_json(doc_dir_existing / "meta.json", doc)
                write_json(index_path, index)
                try:
                    from .index_db import hook_after_source_register

                    hook_after_source_register(index_path, doc)
                except Exception:
                    pass
            return doc

    doc_id = new_id("doc")
    doc_dir = layout_sources_dir / doc_id
    ensure_dir(doc_dir)

    stored_path = None
    if copy_into_sources:
        ext = p.suffix.lower()
        stored_name = f"original{ext}" if ext else "original"
        stored_path = str((doc_dir / stored_name).relative_to(layout_sources_dir.parent))
        shutil.copy2(p, doc_dir / stored_name)

    doc = {
        "docId": doc_id,
        "originalPath": str(p),
        "storedPath": stored_path,
        "sha256": sha,
        "size": p.stat().st_size,
        "addedAt": utc_now_iso(),
    }
    if source_type:
        doc["sourceType"] = source_type
    if extra_meta:
        for k, v in extra_meta.items():
            if k not in doc:
                doc[k] = v

    write_json(doc_dir / "meta.json", doc)

    index.setdefault("docs", []).append(doc)
    write_json(index_path, index)
    try:
        from .index_db import hook_after_source_register

        hook_after_source_register(index_path, doc)
    except Exception:
        pass
    return doc
