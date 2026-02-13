from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .ai_analysis import analyze_spending
from .alerts import run_alerts
from .bootstrap import init_data_layout
from .building import build_daily_monthly_caches
from .ids import new_id
from .layout import Layout
from .reporting import write_daily_report, write_monthly_report
from .storage import read_json, write_json
from .timeutil import today_ymd, utc_now_iso


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return _now()
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _queue_doc(layout: Layout) -> dict[str, Any]:
    doc = read_json(layout.automation_queue_path, {"version": 1, "tasks": []})
    if not isinstance(doc, dict):
        return {"version": 1, "tasks": []}
    tasks = doc.get("tasks")
    if not isinstance(tasks, list):
        doc["tasks"] = []
    return doc


def _write_queue(layout: Layout, doc: dict[str, Any]) -> None:
    write_json(layout.automation_queue_path, doc)


def list_tasks(layout: Layout, *, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
    doc = _queue_doc(layout)
    items = [x for x in doc.get("tasks", []) if isinstance(x, dict)]
    if status:
        wanted = {p.strip() for p in str(status).split(",") if p.strip()}
        items = [x for x in items if str(x.get("status") or "") in wanted]
    items.sort(key=lambda x: str(x.get("createdAt") or ""))
    if limit >= 0:
        items = items[-limit:]
    return items


def enqueue_task(
    layout: Layout,
    *,
    task_type: str,
    payload: dict[str, Any] | None = None,
    run_at: str | None = None,
    max_retries: int = 2,
    source: str = "manual",
) -> dict[str, Any]:
    doc = _queue_doc(layout)
    task = {
        "taskId": new_id("tsk"),
        "taskType": str(task_type),
        "payload": payload or {},
        "status": "queued",
        "attempts": 0,
        "maxRetries": max(0, int(max_retries)),
        "availableAt": _parse_ts(run_at).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "createdAt": utc_now_iso(),
        "updatedAt": utc_now_iso(),
        "source": str(source or "manual"),
    }
    doc.setdefault("tasks", []).append(task)
    _write_queue(layout, doc)
    return task


def _claim_next_task(layout: Layout, *, worker_id: str, lock_ttl_seconds: int = 300) -> dict[str, Any] | None:
    doc = _queue_doc(layout)
    tasks = [x for x in doc.get("tasks", []) if isinstance(x, dict)]
    now = _now()
    lock_ttl = timedelta(seconds=max(1, int(lock_ttl_seconds)))

    def stale_running(x: dict[str, Any]) -> bool:
        if str(x.get("status") or "") != "running":
            return False
        locked_at = _parse_ts(str(x.get("lockedAt") or ""))
        return now - locked_at > lock_ttl

    candidates: list[dict[str, Any]] = []
    for t in tasks:
        st = str(t.get("status") or "")
        if st not in ("queued", "running"):
            continue
        if st == "running" and not stale_running(t):
            continue
        available_at = _parse_ts(str(t.get("availableAt") or ""))
        if available_at <= now:
            candidates.append(t)

    if not candidates:
        return None

    candidates.sort(key=lambda x: str(x.get("availableAt") or ""))
    picked = candidates[0]
    task_id = str(picked.get("taskId") or "")

    for row in tasks:
        if str(row.get("taskId") or "") != task_id:
            continue
        row["status"] = "running"
        row["lockedAt"] = utc_now_iso()
        row["workerId"] = worker_id
        row["updatedAt"] = utc_now_iso()
        row["attempts"] = int(row.get("attempts") or 0) + 1
        break

    doc["tasks"] = tasks
    _write_queue(layout, doc)
    return next((x for x in tasks if str(x.get("taskId") or "") == task_id), None)


def _finish_task(layout: Layout, *, task_id: str, status: str, result: dict[str, Any] | None = None, error: str | None = None, retry_delay_seconds: int = 0) -> dict[str, Any] | None:
    doc = _queue_doc(layout)
    tasks = [x for x in doc.get("tasks", []) if isinstance(x, dict)]
    found: dict[str, Any] | None = None
    for row in tasks:
        if str(row.get("taskId") or "") != str(task_id):
            continue
        row["status"] = status
        row["updatedAt"] = utc_now_iso()
        if result is not None:
            row["result"] = result
        if error is not None:
            row["error"] = error
        if status == "queued" and retry_delay_seconds > 0:
            row["availableAt"] = (_now() + timedelta(seconds=int(retry_delay_seconds))).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            row.pop("lockedAt", None)
            row.pop("workerId", None)
        if status in ("done", "failed"):
            row["finishedAt"] = utc_now_iso()
        found = row
        break
    doc["tasks"] = tasks
    _write_queue(layout, doc)
    return found


def _execute_task(layout: Layout, *, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if task_type == "build":
        return {
            "summary": build_daily_monthly_caches(
                layout,
                from_date=payload.get("fromDate"),
                to_date=payload.get("toDate"),
                include_deleted=bool(payload.get("includeDeleted") or False),
            )
        }

    if task_type == "alerts.run":
        at = str(payload.get("at") or today_ymd())
        commit = bool(payload.get("commit") if "commit" in payload else True)
        return run_alerts(layout, at_date=at, commit=commit)

    if task_type == "ai.analyze":
        month = str(payload.get("month") or today_ymd()[:7])
        provider = str(payload.get("provider") or "auto")
        model = payload.get("model")
        if model is not None:
            model = str(model)
        lookback = int(payload.get("lookbackMonths") or 6)
        return analyze_spending(layout, month=month, provider=provider, model=model, lookback_months=lookback)

    if task_type == "report.daily":
        date = str(payload.get("date") or today_ymd())
        return write_daily_report(layout, date=date)

    if task_type == "report.monthly":
        month = str(payload.get("month") or today_ymd()[:7])
        return write_monthly_report(layout, month=month)

    raise ValueError(f"unsupported taskType: {task_type}")


def run_next_task(layout: Layout, *, worker_id: str = "worker", lock_ttl_seconds: int = 300) -> dict[str, Any]:
    init_data_layout(layout, write_defaults=False)
    task = _claim_next_task(layout, worker_id=worker_id, lock_ttl_seconds=lock_ttl_seconds)
    if not task:
        return {"status": "idle"}

    task_id = str(task.get("taskId") or "")
    task_type = str(task.get("taskType") or "")
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    try:
        result = _execute_task(layout, task_type=task_type, payload=payload)
        done = _finish_task(layout, task_id=task_id, status="done", result=result)
        return {"status": "done", "task": done}
    except Exception as e:
        attempts = int(task.get("attempts") or 1)
        max_retries = int(task.get("maxRetries") or 0)
        if attempts <= max_retries:
            delay = 2 ** max(0, attempts - 1)
            queued = _finish_task(
                layout,
                task_id=task_id,
                status="queued",
                error=str(e),
                retry_delay_seconds=delay,
            )
            return {"status": "retry_scheduled", "task": queued, "error": str(e)}
        failed = _finish_task(layout, task_id=task_id, status="failed", error=str(e))
        return {"status": "failed", "task": failed, "error": str(e)}


def run_worker(
    layout: Layout,
    *,
    worker_id: str = "worker",
    max_tasks: int = 10,
    poll_seconds: float = 0.2,
) -> dict[str, Any]:
    processed = 0
    done = 0
    failed = 0
    retried = 0
    for _ in range(max(1, int(max_tasks))):
        res = run_next_task(layout, worker_id=worker_id)
        if res.get("status") == "idle":
            break
        processed += 1
        st = str(res.get("status") or "")
        if st == "done":
            done += 1
        elif st == "failed":
            failed += 1
        elif st == "retry_scheduled":
            retried += 1
        if poll_seconds > 0:
            time.sleep(poll_seconds)
    return {"processed": processed, "done": done, "failed": failed, "retried": retried}


def _load_jobs(layout: Layout) -> list[dict[str, Any]]:
    doc = read_json(layout.automation_jobs_path, {"version": 1, "jobs": []})
    jobs = doc.get("jobs") if isinstance(doc, dict) else []
    return [x for x in jobs if isinstance(x, dict)]


def _load_state(layout: Layout) -> dict[str, Any]:
    doc = read_json(layout.automation_state_path, {"version": 1, "lastSlots": {}})
    if not isinstance(doc, dict):
        return {"version": 1, "lastSlots": {}}
    if not isinstance(doc.get("lastSlots"), dict):
        doc["lastSlots"] = {}
    return doc


def _write_state(layout: Layout, state: dict[str, Any]) -> None:
    write_json(layout.automation_state_path, state)


def _weekday_name(dt: datetime) -> str:
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return names[dt.weekday()]


def _job_slot(job: dict[str, Any], *, at: datetime) -> str | None:
    schedule = job.get("schedule") if isinstance(job.get("schedule"), dict) else {}
    freq = str(schedule.get("freq") or "daily").lower()

    if freq == "daily":
        at_hm = str(schedule.get("at") or "00:00")
        hh, mm = [int(x) for x in at_hm.split(":", 1)]
        run_at = at.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if at >= run_at:
            return f"daily:{at.date().isoformat()}:{at_hm}"
        return None

    if freq == "weekly":
        day = str(schedule.get("day") or "mon").lower()
        at_hm = str(schedule.get("at") or "00:00")
        if _weekday_name(at) != day:
            return None
        hh, mm = [int(x) for x in at_hm.split(":", 1)]
        run_at = at.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if at >= run_at:
            return f"weekly:{at.date().isoformat()}:{at_hm}:{day}"
        return None

    if freq == "hourly":
        interval = max(1, int(schedule.get("interval") or 1))
        slot_hour = at.replace(minute=0, second=0, microsecond=0)
        if (slot_hour.hour % interval) == 0:
            return f"hourly:{slot_hour.isoformat().replace('+00:00', 'Z')}:i{interval}"
        return None

    return None


def enqueue_due_jobs(layout: Layout, *, at: str | None = None) -> dict[str, Any]:
    init_data_layout(layout, write_defaults=False)
    jobs = _load_jobs(layout)
    state = _load_state(layout)
    last_slots = state.get("lastSlots") if isinstance(state.get("lastSlots"), dict) else {}
    now = _parse_ts(at)

    created: list[str] = []
    skipped: list[str] = []
    for job in jobs:
        if not bool(job.get("enabled", True)):
            continue
        job_id = str(job.get("id") or "")
        if not job_id:
            continue
        slot = _job_slot(job, at=now)
        if not slot:
            continue
        if str(last_slots.get(job_id) or "") == slot:
            skipped.append(job_id)
            continue

        task = job.get("task") if isinstance(job.get("task"), dict) else {}
        task_type = str(task.get("type") or "").strip()
        if not task_type:
            continue
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        max_retries = int(task.get("maxRetries") or 2)
        enqueue_task(
            layout,
            task_type=task_type,
            payload=payload,
            run_at=now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            max_retries=max_retries,
            source=f"job:{job_id}",
        )
        last_slots[job_id] = slot
        created.append(job_id)

    state["lastSlots"] = last_slots
    _write_state(layout, state)
    return {"created": len(created), "createdJobIds": created, "skippedJobIds": skipped}


def read_jobs(layout: Layout) -> dict[str, Any]:
    return read_json(layout.automation_jobs_path, {"version": 1, "jobs": []})


def write_jobs(layout: Layout, doc: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise ValueError("jobs payload must be an object")
    jobs = doc.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("jobs must be a list")
    for row in jobs:
        if not isinstance(row, dict):
            raise ValueError("each job must be an object")
        if not str(row.get("id") or "").strip():
            raise ValueError("each job requires id")
        task = row.get("task") if isinstance(row.get("task"), dict) else {}
        if not str(task.get("type") or "").strip():
            raise ValueError(f"job {row.get('id')} requires task.type")
    out = {"version": int(doc.get("version") or 1), "jobs": jobs}
    write_json(layout.automation_jobs_path, out)
    return out
