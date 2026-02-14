from __future__ import annotations

import os
import shutil
import tarfile
from pathlib import Path
from typing import Any

from .layout import Layout
from .storage import ensure_dir
from .timeutil import utc_now_iso


def _default_backup_path(layout: Layout) -> Path:
    out_dir = ensure_dir(layout.data_dir.parent / "ledgerflow_backups")
    stamp = utc_now_iso().replace(":", "").replace("-", "").replace("T", "-").replace("Z", "")
    return out_dir / f"ledgerflow-{stamp}.tar.gz"


def create_backup(
    layout: Layout,
    *,
    out_path: str | Path | None = None,
    include_inbox: bool = True,
) -> dict[str, Any]:
    src_root = layout.data_dir.resolve()
    out = Path(out_path).expanduser().resolve() if out_path else _default_backup_path(layout).resolve()
    ensure_dir(out.parent)

    file_count = 0
    with tarfile.open(out, mode="w:gz") as tf:
        for p in src_root.rglob("*"):
            if not p.is_file():
                continue
            rp = p.resolve()
            if rp == out:
                continue
            rel = rp.relative_to(src_root)
            if not include_inbox and (rel.parts and rel.parts[0] == "inbox"):
                continue
            tf.add(rp, arcname=str(rel), recursive=False)
            file_count += 1

    size = out.stat().st_size if out.exists() else 0
    return {
        "archivePath": str(out),
        "sizeBytes": int(size),
        "fileCount": int(file_count),
        "includeInbox": bool(include_inbox),
        "createdAt": utc_now_iso(),
    }


def _safe_extract(tf: tarfile.TarFile, target: Path) -> int:
    target_resolved = target.resolve()
    members = tf.getmembers()
    for member in members:
        name = str(member.name or "")
        if not name or name.startswith("/"):
            raise ValueError("invalid archive member path")
        dest = (target_resolved / name).resolve()
        if not str(dest).startswith(str(target_resolved) + os.sep) and dest != target_resolved:
            raise ValueError("archive contains path traversal entries")
    tf.extractall(path=str(target_resolved), members=members)
    return len(members)


def restore_backup(
    archive_path: str | Path,
    *,
    target_dir: str | Path,
    force: bool = False,
) -> dict[str, Any]:
    archive = Path(archive_path).expanduser().resolve()
    if not archive.exists() or not archive.is_file():
        raise ValueError("archivePath does not exist")

    target = Path(target_dir).expanduser().resolve()
    if target.exists():
        has_content = any(target.iterdir())
        if has_content and not force:
            raise ValueError("targetDir is not empty; pass force=true to overwrite")
        if has_content and force:
            shutil.rmtree(target)
    ensure_dir(target)

    with tarfile.open(archive, mode="r:gz") as tf:
        extracted = _safe_extract(tf, target)

    return {
        "archivePath": str(archive),
        "targetDir": str(target),
        "extractedEntries": int(extracted),
        "restoredAt": utc_now_iso(),
    }
