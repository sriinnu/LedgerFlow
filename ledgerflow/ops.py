from __future__ import annotations

from pathlib import Path
from typing import Any

from .automation import queue_stats
from .index_db import index_stats
from .layout import Layout
from .storage import read_json
from .timeutil import utc_now_iso


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _sources_count(layout: Layout) -> int:
    idx = read_json(layout.sources_index_path, {"version": 1, "docs": []})
    docs = idx.get("docs") if isinstance(idx, dict) else []
    if isinstance(docs, list):
        return len(docs)
    return 0


def collect_metrics(layout: Layout) -> dict[str, Any]:
    idx = index_stats(layout)
    queue = queue_stats(layout)
    return {
        "generatedAt": utc_now_iso(),
        "dataDir": str(layout.data_dir),
        "index": idx,
        "queue": queue,
        "counts": {
            "sources": _sources_count(layout),
            "alertsEvents": _count_jsonl(layout.alerts_dir / "events.jsonl"),
            "alertsOutbox": _count_jsonl(layout.alert_outbox_path),
            "auditEvents": _count_jsonl(layout.audit_log_path),
            "transactionsJsonl": _count_jsonl(layout.transactions_path),
            "correctionsJsonl": _count_jsonl(layout.corrections_path),
        },
    }
