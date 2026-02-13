from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledgerflow.automation import enqueue_due_jobs, enqueue_task, list_tasks, read_jobs, run_next_task, run_worker, write_jobs
from ledgerflow.bootstrap import init_data_layout
from ledgerflow.layout import layout_for


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


if __name__ == "__main__":
    unittest.main()
