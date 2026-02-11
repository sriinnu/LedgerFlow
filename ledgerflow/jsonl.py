from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def iter_jsonl(path: str | Path) -> Any:
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def read_jsonl(path: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    """
    Read JSONL into memory. If limit is provided, returns the last N items.
    Suitable for MVP/local usage (not optimized for huge files).
    """
    p = Path(path)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    if limit is not None and limit >= 0:
        lines = lines[-limit:]

    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out
