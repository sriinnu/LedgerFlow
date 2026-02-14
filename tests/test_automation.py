from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledgerflow.automation import dispatch_due_and_work, enqueue_due_jobs, enqueue_task, list_dead_letters, list_tasks, queue_stats, read_jobs, run_next_task, run_worker, write_jobs
from ledgerflow.bootstrap import init_data_layout
from ledgerflow.layout import layout_for
from ledgerflow.storage import append_jsonl


class TestAutomation(unittest.TestCase):
    def test_enqueue_and_run_next(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)

            task = enqueue_task(layout, task_type="build", payload={})
            self.assertEqual(task["status"], "queued")

            before = list_tasks(layout)
            self.assertEqual(len(before), 1)

            res = run_next_task(layout, worker_id="t1")
            self.assertEqual(res["status"], "done")
            self.assertEqual((res.get("task") or {}).get("taskType"), "build")

            idle = run_next_task(layout, worker_id="t1")
            self.assertEqual(idle["status"], "idle")

    def test_run_next_retry_and_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)

            enqueue_task(layout, task_type="unknown.task", payload={}, max_retries=1)

            first = run_next_task(layout, worker_id="t2")
            self.assertEqual(first["status"], "retry_scheduled")

            queued = list_tasks(layout, status="queued")
            self.assertEqual(len(queued), 1)
            # Force immediate retry.
            queued[0]["availableAt"] = "1970-01-01T00:00:00Z"
            from ledgerflow.storage import write_json

            write_json(layout.automation_queue_path, {"version": 1, "tasks": queued})

            second = run_next_task(layout, worker_id="t2")
            self.assertEqual(second["status"], "failed")

    def test_enqueue_due_jobs_once_per_slot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)

            jobs = {
                "version": 1,
                "jobs": [
                    {
                        "id": "daily_build",
                        "enabled": True,
                        "schedule": {"freq": "daily", "at": "08:00"},
                        "task": {"type": "build", "payload": {}},
                    }
                ],
            }
            write_jobs(layout, jobs)

            r1 = enqueue_due_jobs(layout, at="2026-02-10T08:10:00Z")
            self.assertEqual(r1["created"], 1)

            r2 = enqueue_due_jobs(layout, at="2026-02-10T08:20:00Z")
            self.assertEqual(r2["created"], 0)

            queue = list_tasks(layout)
            self.assertEqual(len(queue), 1)

    def test_jobs_roundtrip_and_worker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)

            initial = read_jobs(layout)
            self.assertIn("jobs", initial)

            enqueue_task(layout, task_type="build", payload={})
            enqueue_task(layout, task_type="build", payload={})
            out = run_worker(layout, worker_id="w1", max_tasks=5, poll_seconds=0)
            self.assertEqual(out["processed"], 2)
            self.assertEqual(out["done"], 2)

    def test_dead_letter_and_stats(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)

            enqueue_task(layout, task_type="unknown.task", payload={}, max_retries=0)
            res = run_next_task(layout, worker_id="w2")
            self.assertEqual(res["status"], "failed")

            stats = queue_stats(layout)
            self.assertGreaterEqual(stats.get("deadLetterCount") or 0, 1)
            self.assertGreaterEqual((stats.get("counts") or {}).get("failed") or 0, 1)

            dls = list_dead_letters(layout, limit=10)
            self.assertGreaterEqual(len(dls), 1)
            self.assertEqual(dls[0].get("taskType"), "unknown.task")

    def test_dispatch_due_and_work(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)

            jobs = {
                "version": 1,
                "jobs": [
                    {
                        "id": "daily_build",
                        "enabled": True,
                        "schedule": {"freq": "daily", "at": "10:00"},
                        "task": {"type": "build", "payload": {}},
                    }
                ],
            }
            write_jobs(layout, jobs)

            out = dispatch_due_and_work(layout, at="2026-02-10T10:05:00Z", worker_id="disp", max_tasks=5, poll_seconds=0)
            self.assertEqual((out.get("due") or {}).get("created"), 1)
            self.assertGreaterEqual(((out.get("worker") or {}).get("processed") or 0), 1)

    def test_invalid_job_schedule_validation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)

            bad = {
                "version": 1,
                "jobs": [
                    {
                        "id": "bad_weekly",
                        "enabled": True,
                        "schedule": {"freq": "weekly", "at": "09:00", "day": "monday"},
                        "task": {"type": "build", "payload": {}},
                    }
                ],
            }
            with self.assertRaises(ValueError):
                write_jobs(layout, bad)

    def test_alerts_deliver_task_type(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)

            append_jsonl(
                layout.alerts_dir / "events.jsonl",
                {
                    "eventId": "alrt_1",
                    "ruleId": "t",
                    "type": "category_budget",
                    "period": "day",
                    "periodKey": "2026-02-10",
                    "scopeDate": "2026-02-10",
                    "at": "2026-02-10T00:00:00Z",
                    "data": {},
                    "message": "test",
                },
            )
            enqueue_task(layout, task_type="alerts.deliver", payload={"limit": 10})
            res = run_next_task(layout, worker_id="t-deliver")
            self.assertEqual(res["status"], "done")
            out = (((res.get("task") or {}).get("result") or {}))
            self.assertEqual(int(out.get("delivered") or 0), 1)


if __name__ == "__main__":
    unittest.main()
