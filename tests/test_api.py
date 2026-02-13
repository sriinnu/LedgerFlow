from __future__ import annotations

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
            self.assertIn("Non-local API access requires", denied.text)
