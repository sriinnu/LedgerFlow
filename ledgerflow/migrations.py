from __future__ import annotations

from typing import Any

from .bootstrap import init_data_layout
from .index_db import rebuild_index
from .layout import Layout
from .storage import ensure_dir, read_json, write_json
from .timeutil import utc_now_iso

APP_SCHEMA_VERSION = 2


def _default_state() -> dict[str, Any]:
    return {"version": 0, "updatedAt": None, "history": []}


def get_state(layout: Layout) -> dict[str, Any]:
    return read_json(layout.schema_state_path, _default_state())


def status(layout: Layout) -> dict[str, Any]:
    st = get_state(layout)
    cur = int(st.get("version") or 0)
    return {
        "currentVersion": cur,
        "latestVersion": APP_SCHEMA_VERSION,
        "pending": max(0, APP_SCHEMA_VERSION - cur),
        "schemaStatePath": str(layout.schema_state_path),
    }


def _append_history(st: dict[str, Any], step: int, note: str) -> None:
    st.setdefault("history", []).append({"step": step, "note": note, "at": utc_now_iso()})
    st["updatedAt"] = utc_now_iso()


def migrate_to_latest(layout: Layout, *, target_version: int | None = None) -> dict[str, Any]:
    target = target_version if target_version is not None else APP_SCHEMA_VERSION
    if target < 0:
        raise ValueError("target_version must be >= 0")
    target = min(target, APP_SCHEMA_VERSION)

    ensure_dir(layout.meta_dir)
    st = get_state(layout)
    cur = int(st.get("version") or 0)
    from_version = cur

    applied: list[int] = []
    while cur < target:
        nxt = cur + 1
        if nxt == 1:
            # Base layout + defaults.
            init_data_layout(layout, write_defaults=True)
            _append_history(st, 1, "Initialized data layout and defaults.")
        elif nxt == 2:
            # SQLite index backfill.
            init_data_layout(layout, write_defaults=False)
            res = rebuild_index(layout)
            _append_history(st, 2, f"Rebuilt sqlite index: {res}")
        else:
            raise ValueError(f"Unsupported migration step: {nxt}")

        cur = nxt
        st["version"] = cur
        applied.append(cur)
        write_json(layout.schema_state_path, st)

    return {"fromVersion": from_version, "toVersion": cur, "applied": applied}
