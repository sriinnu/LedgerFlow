from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ledgerflow.server import create_app


class TestApi(unittest.TestCase):
    def test_health_and_manual_add(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            app = create_app(str(data_dir))
            client = TestClient(app)

            h = client.get("/api/health")
            self.assertEqual(h.status_code, 200)
            self.assertEqual(h.json()["status"], "ok")
            self.assertEqual(h.json().get("authMode"), "local_only_no_key")

            caps = client.get("/api/ocr/capabilities")
            self.assertEqual(caps.status_code, 200)
            self.assertIn("image_ocr_available", caps.json())

            idx = client.get("/api/index/stats")
            self.assertEqual(idx.status_code, 200)
            self.assertIn("transactions", idx.json())

            mig = client.get("/api/migrate/status")
            self.assertEqual(mig.status_code, 200)
            self.assertIn("latestVersion", mig.json())

            res = client.post(
                "/api/manual/add",
                json={
                    "occurredAt": "2026-02-10",
                    "amount": {"value": "-12.30", "currency": "USD"},
                    "merchant": "Farmers Market",
                    "description": "cash vegetables",
                    "categoryHint": "groceries",
                    "tags": ["cash"],
                    "links": {},
                },
            )
            self.assertEqual(res.status_code, 200)
            tx = res.json()["tx"]
            self.assertEqual(tx["merchant"], "Farmers Market")

            txs = client.get("/api/transactions?limit=10").json()["items"]
            self.assertEqual(len(txs), 1)

    def test_ocr_extract_path_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            app = create_app(str(data_dir))
            client = TestClient(app)

            txt = Path(td) / "receipt.txt"
            txt.write_text("HELLO OCR", encoding="utf-8")

            r = client.post(
                "/api/ocr/extract-path",
                json={"path": str(txt), "imageProvider": "auto", "preprocess": True},
            )
            self.assertEqual(r.status_code, 200)
            j = r.json()
            self.assertEqual(j["meta"]["method"], "text")
            self.assertEqual(j["text"], "HELLO OCR")

    def test_import_csv_upload_commit_and_dedup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            app = create_app(str(data_dir))
            client = TestClient(app)

            csv_data = (
                "Date,Description,Amount,Currency\n"
                "2026-02-10,FARMERS MARKET,-12.30,USD\n"
                "2026-02-11,SALARY,1000.00,USD\n"
            ).encode("utf-8")

            # Commit first time.
            r1 = client.post(
                "/api/import/csv-upload",
                data={"commit": "true", "currency": "USD"},
                files={"file": ("bank.csv", csv_data, "text/csv")},
            )
            self.assertEqual(r1.status_code, 200)
            j1 = r1.json()
            self.assertEqual(j1["mode"], "commit")
            self.assertEqual(j1["imported"], 2)

            # Commit again (same content) should skip.
            r2 = client.post(
                "/api/import/csv-upload",
                data={"commit": "true", "currency": "USD"},
                files={"file": ("bank.csv", csv_data, "text/csv")},
            )
            self.assertEqual(r2.status_code, 200)
            j2 = r2.json()
            self.assertEqual(j2["imported"], 0)
            self.assertEqual(j2["skipped"], 2)

    def test_reports_charts_alerts_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            app = create_app(str(data_dir))
            client = TestClient(app)

            # Seed a tx via manual API.
            client.post(
                "/api/manual/add",
                json={
                    "occurredAt": "2026-02-10",
                    "amount": {"value": "-12.30", "currency": "USD"},
                    "merchant": "Farmers Market",
                    "description": "cash vegetables",
                    "categoryHint": "groceries",
                    "tags": ["cash"],
                    "links": {},
                },
            )

            # Build caches.
            b = client.post("/api/build", json={})
            self.assertEqual(b.status_code, 200)

            # Daily report create + fetch.
            r = client.post("/api/report/daily", json={"date": "2026-02-10"})
            self.assertEqual(r.status_code, 200)
            g = client.get("/api/report/daily/2026-02-10")
            self.assertEqual(g.status_code, 200)
            self.assertIn("Daily Report", g.text)

            # Monthly report create + fetch.
            rm = client.post("/api/report/monthly", json={"month": "2026-02"})
            self.assertEqual(rm.status_code, 200)
            gm = client.get("/api/report/monthly/2026-02")
            self.assertEqual(gm.status_code, 200)
            self.assertIn("Monthly Report", gm.text)

            # Charts.
            cs = client.post("/api/charts/series", json={"fromDate": "2026-02-10", "toDate": "2026-02-10"})
            self.assertEqual(cs.status_code, 200)
            self.assertIn("points", cs.json()["data"])

            cm = client.post("/api/charts/month", json={"month": "2026-02", "limit": 10})
            self.assertEqual(cm.status_code, 200)
            self.assertIn("totals", cm.json()["categoryBreakdown"])

            # Alerts.
            ar = client.post("/api/alerts/run", json={"at": "2026-02-10", "commit": False})
            self.assertEqual(ar.status_code, 200)

            event = {
                "eventId": "alrt_test_1",
                "ruleId": "test_rule",
                "type": "category_budget",
                "period": "day",
                "periodKey": "2026-02-10",
                "scopeDate": "2026-02-10",
                "at": "2026-02-10T00:00:00Z",
                "data": {"limit": "10", "value": "20"},
                "message": "test",
            }
            events_path = data_dir / "alerts" / "events.jsonl"
            events_path.parent.mkdir(parents=True, exist_ok=True)
            events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

            ad = client.post("/api/alerts/deliver", json={"limit": 10})
            self.assertEqual(ad.status_code, 200)
            self.assertEqual(ad.json().get("delivered"), 1)

            ao = client.get("/api/alerts/outbox?limit=10")
            self.assertEqual(ao.status_code, 200)
            self.assertEqual(len(ao.json().get("items") or []), 1)

            ai = client.post("/api/ai/analyze", json={"month": "2026-02", "provider": "heuristic", "lookbackMonths": 3})
            self.assertEqual(ai.status_code, 200)
            aj = ai.json()
            self.assertEqual(aj["providerUsed"], "heuristic")
            self.assertIn("datasets", aj)

    def test_review_queue_and_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            app = create_app(str(data_dir))
            client = TestClient(app)

            add = client.post(
                "/api/manual/add",
                json={
                    "occurredAt": "2026-02-10",
                    "amount": {"value": "-12.30", "currency": "USD"},
                    "merchant": "Farmers Market",
                    "description": "",
                    "tags": ["cash"],
                    "links": {},
                },
            )
            self.assertEqual(add.status_code, 200)
            tx_id = add.json()["tx"]["txId"]

            q1 = client.get("/api/review/queue?date=2026-02-10&limit=100")
            self.assertEqual(q1.status_code, 200)
            items = q1.json()["items"]
            self.assertTrue(any((i.get("txId") == tx_id and i.get("kind") == "transaction") for i in items))

            r = client.post(
                "/api/review/resolve",
                json={
                    "txId": tx_id,
                    "patch": {"category": {"id": "groceries", "confidence": 1.0, "reason": "review_resolve"}},
                },
            )
            self.assertEqual(r.status_code, 200)

            q2 = client.get("/api/review/queue?date=2026-02-10&limit=100")
            self.assertEqual(q2.status_code, 200)
            items2 = q2.json()["items"]
            self.assertFalse(any((i.get("txId") == tx_id and i.get("kind") == "transaction") for i in items2))

    def test_api_key_auth_and_audit_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            with patch.dict("os.environ", {"LEDGERFLOW_API_KEY": "secret-key"}, clear=False):
                app = create_app(str(data_dir))
            client = TestClient(app)

            h = client.get("/api/health")
            self.assertEqual(h.status_code, 200)
            self.assertTrue(h.json().get("authEnabled"))
            self.assertEqual(h.json().get("authMode"), "api_key")

            denied = client.post(
                "/api/manual/add",
                json={
                    "occurredAt": "2026-02-10",
                    "amount": {"value": "-12.30", "currency": "USD"},
                    "merchant": "Farmers Market",
                },
            )
            self.assertEqual(denied.status_code, 401)

            ok = client.post(
                "/api/manual/add",
                headers={"x-api-key": "secret-key"},
                json={
                    "occurredAt": "2026-02-10",
                    "amount": {"value": "-12.30", "currency": "USD"},
                    "merchant": "Farmers Market",
                },
            )
            self.assertEqual(ok.status_code, 200)

            events = client.get("/api/audit/events?limit=20", headers={"x-api-key": "secret-key"})
            self.assertEqual(events.status_code, 200)
            items = events.json()["items"]
            self.assertGreaterEqual(len(items), 2)
            self.assertTrue(any(i.get("authDenied") is True for i in items))
            self.assertTrue(any(i.get("status") == 200 for i in items))

    def test_non_local_without_api_key_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            app = create_app(str(data_dir))
            client = TestClient(app)

            with patch("ledgerflow.server._is_local_client", return_value=False):
                denied = client.post(
                    "/api/manual/add",
                    json={
                        "occurredAt": "2026-02-10",
                        "amount": {"value": "-12.30", "currency": "USD"},
                        "merchant": "Farmers Market",
                    },
                )

            self.assertEqual(denied.status_code, 401)

    def test_scoped_api_keys_read_vs_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            scoped = json.dumps(
                [
                    {"id": "reader", "key": "read-only", "scopes": ["read"]},
                    {"id": "writer", "key": "write-ok", "scopes": ["write"]},
                ]
            )
            with patch.dict("os.environ", {"LEDGERFLOW_API_KEYS": scoped, "LEDGERFLOW_API_KEY": ""}, clear=False):
                app = create_app(str(data_dir))
            client = TestClient(app)

            h = client.get("/api/health")
            self.assertEqual(h.status_code, 200)
            self.assertTrue(h.json().get("authEnabled"))
            self.assertEqual(h.json().get("authMode"), "api_key_scoped")

            read_ok = client.get("/api/transactions?limit=10", headers={"x-api-key": "read-only"})
            self.assertEqual(read_ok.status_code, 200)

            denied = client.post(
                "/api/manual/add",
                headers={"x-api-key": "read-only"},
                json={
                    "occurredAt": "2026-02-10",
                    "amount": {"value": "-12.30", "currency": "USD"},
                    "merchant": "Farmers Market",
                },
            )
            self.assertEqual(denied.status_code, 403)

            write_ok = client.post(
                "/api/manual/add",
                headers={"x-api-key": "write-ok"},
                json={
                    "occurredAt": "2026-02-10",
                    "amount": {"value": "-12.30", "currency": "USD"},
                    "merchant": "Farmers Market",
                },
            )
            self.assertEqual(write_ok.status_code, 200)

            ctx = client.get("/api/auth/context", headers={"x-api-key": "write-ok"})
            self.assertEqual(ctx.status_code, 200)
            self.assertTrue(ctx.json().get("authenticated"))
            self.assertIn("write", ctx.json().get("scopes") or [])

    def test_scoped_api_keys_disabled_and_expired(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            scoped = json.dumps(
                [
                    {"id": "disabled", "key": "off-key", "scopes": ["write"], "enabled": False},
                    {"id": "expired", "key": "old-key", "scopes": ["write"], "expiresAt": "2020-01-01T00:00:00Z"},
                    {"id": "active", "key": "good-key", "scopes": ["write"], "expiresAt": "2099-01-01T00:00:00Z"},
                    {"id": "admin", "key": "admin-key", "role": "admin"},
                ]
            )
            with patch.dict("os.environ", {"LEDGERFLOW_API_KEYS": scoped, "LEDGERFLOW_API_KEY": ""}, clear=False):
                app = create_app(str(data_dir))
            client = TestClient(app)

            r1 = client.post(
                "/api/manual/add",
                headers={"x-api-key": "off-key"},
                json={"occurredAt": "2026-02-10", "amount": {"value": "-10", "currency": "USD"}, "merchant": "x"},
            )
            self.assertEqual(r1.status_code, 401)

            r2 = client.post(
                "/api/manual/add",
                headers={"x-api-key": "old-key"},
                json={"occurredAt": "2026-02-10", "amount": {"value": "-10", "currency": "USD"}, "merchant": "x"},
            )
            self.assertEqual(r2.status_code, 401)

            r3 = client.post(
                "/api/manual/add",
                headers={"x-api-key": "good-key"},
                json={"occurredAt": "2026-02-10", "amount": {"value": "-10", "currency": "USD"}, "merchant": "x"},
            )
            self.assertEqual(r3.status_code, 200)

            keys = client.get("/api/auth/keys", headers={"x-api-key": "admin-key"})
            self.assertEqual(keys.status_code, 200)
            self.assertGreaterEqual(keys.json().get("count") or 0, 3)

    def test_rbac_feature_scopes_and_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            scoped = json.dumps(
                [
                    {"id": "writer", "key": "writer-key", "scopes": ["write"]},
                    {"id": "ops", "key": "ops-key", "scopes": ["read", "ops"]},
                    {"id": "auto", "key": "auto-key", "scopes": ["read", "write", "automation"]},
                    {"id": "admin", "key": "admin-key", "role": "admin"},
                    {"id": "team-a", "key": "team-a-key", "scopes": ["read"], "workspaces": ["team-a"]},
                ]
            )
            with patch.dict("os.environ", {"LEDGERFLOW_API_KEYS": scoped, "LEDGERFLOW_API_KEY": ""}, clear=False):
                app = create_app(str(data_dir))
            client = TestClient(app)

            # writer lacks automation scope
            d1 = client.post("/api/automation/tasks", headers={"x-api-key": "writer-key"}, json={"taskType": "build", "payload": {}})
            self.assertEqual(d1.status_code, 403)

            # auto key has write + automation
            ok1 = client.post("/api/automation/tasks", headers={"x-api-key": "auto-key"}, json={"taskType": "build", "payload": {}})
            self.assertEqual(ok1.status_code, 200)

            # backup requires admin
            d2 = client.post("/api/backup/create", headers={"x-api-key": "writer-key"}, json={})
            self.assertEqual(d2.status_code, 403)
            ok2 = client.post("/api/backup/create", headers={"x-api-key": "admin-key"}, json={"includeInbox": False})
            self.assertEqual(ok2.status_code, 200)

            # ops endpoint requires ops scope
            d3 = client.get("/api/ops/metrics", headers={"x-api-key": "writer-key"})
            self.assertEqual(d3.status_code, 403)
            ok3 = client.get("/api/ops/metrics", headers={"x-api-key": "ops-key"})
            self.assertEqual(ok3.status_code, 200)

            # alert delivery requires automation scope
            d4 = client.post("/api/alerts/deliver", headers={"x-api-key": "writer-key"}, json={})
            self.assertEqual(d4.status_code, 403)
            ok4 = client.post("/api/alerts/deliver", headers={"x-api-key": "auto-key"}, json={"dryRun": True})
            self.assertEqual(ok4.status_code, 200)

            # workspace restrictions
            d5 = client.get(
                "/api/transactions?limit=5",
                headers={"x-api-key": "team-a-key", "x-workspace-id": "team-b"},
            )
            self.assertEqual(d5.status_code, 403)
            ok5 = client.get(
                "/api/transactions?limit=5",
                headers={"x-api-key": "team-a-key", "x-workspace-id": "team-a"},
            )
            self.assertEqual(ok5.status_code, 200)

    def test_automation_and_bank_json_api_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            app = create_app(str(data_dir))
            client = TestClient(app)

            enq = client.post("/api/automation/tasks", json={"taskType": "build", "payload": {}})
            self.assertEqual(enq.status_code, 200)
            task_id = enq.json()["task"]["taskId"]
            self.assertTrue(task_id.startswith("tsk_"))

            tasks = client.get("/api/automation/tasks?limit=20")
            self.assertEqual(tasks.status_code, 200)
            self.assertGreaterEqual(tasks.json()["count"], 1)

            stats1 = client.get("/api/automation/stats")
            self.assertEqual(stats1.status_code, 200)
            self.assertIn("counts", stats1.json())

            run1 = client.post("/api/automation/run-next", json={"workerId": "api-test"})
            self.assertEqual(run1.status_code, 200)
            self.assertIn(run1.json()["status"], {"done", "retry_scheduled", "failed"})

            jobs_doc = {
                "version": 1,
                "jobs": [
                    {
                        "id": "daily_build",
                        "enabled": True,
                        "schedule": {"freq": "daily", "at": "09:00"},
                        "task": {"type": "build", "payload": {}},
                    }
                ],
            }
            sj = client.post("/api/automation/jobs", json=jobs_doc)
            self.assertEqual(sj.status_code, 200)
            gj = client.get("/api/automation/jobs")
            self.assertEqual(gj.status_code, 200)
            self.assertEqual(len(gj.json().get("jobs") or []), 1)

            due = client.post("/api/automation/run-due", json={"at": "2026-02-10T09:05:00Z"})
            self.assertEqual(due.status_code, 200)
            self.assertEqual(due.json().get("created"), 1)

            disp = client.post("/api/automation/dispatch", json={"runDue": True, "at": "2026-02-10T09:10:00Z", "maxTasks": 5})
            self.assertEqual(disp.status_code, 200)
            self.assertIn("queueStats", disp.json())

            bank_json = Path(td) / "bank.json"
            bank_json.write_text(
                json.dumps(
                    {
                        "transactions": [
                            {"date": "2026-02-10", "amount": -9.99, "currency": "USD", "merchant": "Cafe"},
                            {"date": "2026-02-11", "amount": 100.0, "currency": "USD", "merchant": "Payroll"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            bj = client.post(
                "/api/import/bank-json-path",
                json={"path": str(bank_json), "commit": True, "currency": "USD"},
            )
            self.assertEqual(bj.status_code, 200)
            self.assertEqual(bj.json().get("imported"), 2)

            nested = Path(td) / "bank_nested.json"
            nested.write_text(
                json.dumps(
                    {
                        "transactions": [
                            {
                                "meta": {"date": "2026-02-12", "merchant": {"name": "Metro"}},
                                "money": {"value": "-7.25", "currency": "USD"},
                                "notes": {"text": "subway"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            bj2 = client.post(
                "/api/import/bank-json-path",
                json={
                    "path": str(nested),
                    "commit": True,
                    "currency": "USD",
                    "mapping": {
                        "date": "meta.date",
                        "merchant": "meta.merchant.name",
                        "amount": "money.value",
                        "currency": "money.currency",
                        "description": "notes.text",
                    },
                },
            )
            self.assertEqual(bj2.status_code, 200)
            self.assertEqual(bj2.json().get("imported"), 1)

            dead = client.get("/api/automation/dead-letters?limit=20")
            self.assertEqual(dead.status_code, 200)
            self.assertIn("items", dead.json())

            cons = client.get("/api/connectors")
            self.assertEqual(cons.status_code, 200)
            self.assertTrue(any((x.get("id") == "plaid") for x in (cons.json().get("items") or [])))

            plaid = Path(td) / "plaid.json"
            plaid.write_text(
                json.dumps(
                    {
                        "transactions": [
                            {
                                "date": "2026-02-13",
                                "name": "Coffee Shop",
                                "merchant_name": "Coffee Shop",
                                "amount": 4.75,
                                "iso_currency_code": "USD",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            imp_conn = client.post(
                "/api/import/connector-path",
                json={
                    "connector": "plaid",
                    "path": str(plaid),
                    "commit": True,
                    "currency": "USD",
                },
            )
            self.assertEqual(imp_conn.status_code, 200)
            self.assertEqual(imp_conn.json().get("imported"), 1)

            backup = client.post("/api/backup/create", json={"includeInbox": False})
            self.assertEqual(backup.status_code, 200)
            archive_path = backup.json().get("archivePath")
            self.assertTrue(isinstance(archive_path, str) and len(archive_path) > 0)

            restore_target = str(Path(td) / "restored_api")
            restored = client.post(
                "/api/backup/restore",
                json={"archivePath": archive_path, "targetDir": restore_target, "force": True},
            )
            self.assertEqual(restored.status_code, 200)
            self.assertTrue((Path(restore_target) / "ledger" / "transactions.jsonl").exists())

            metrics = client.get("/api/ops/metrics")
            self.assertEqual(metrics.status_code, 200)
            mj = metrics.json()
            self.assertIn("index", mj)
            self.assertIn("queue", mj)
            self.assertIn("counts", mj)
