from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .alerts import run_alerts
from .bootstrap import init_data_layout
from .building import build_daily_monthly_caches
from .charts import build_category_breakdown_month, build_series, build_merchant_top_month
from .csv_import import CsvMapping, csv_row_to_tx, infer_mapping, read_csv_rows
from .dedup import mark_manual_duplicates_against_bank
from .documents import import_and_parse_bill, import_and_parse_receipt
from .extraction import extract_text, ocr_capabilities
from .exporting import export_transactions_csv
from .index_db import has_source_hash, index_stats, recent_transactions, rebuild_index
from .jsonl import read_jsonl
from .layout import Layout, layout_for
from .linking import link_bills_to_bank, link_receipts_to_bank
from .manual import ManualEntry, correction_event, manual_entry_to_tx, parse_amount, tombstone_event
from .migrations import APP_SCHEMA_VERSION, migrate_to_latest, status as migration_status
from .reporting import daily_report_data, render_daily_report_md, monthly_report_data, render_monthly_report_md, write_daily_report, write_monthly_report
from .review import resolve_review_transaction, review_queue
from .sources import register_file
from .storage import append_jsonl, ensure_dir, read_json
from .timeutil import parse_ymd, today_ymd, utc_now_iso


def _get_layout(request: Request) -> Layout:
    layout = getattr(request.app.state, "layout", None)
    if not isinstance(layout, Layout):
        raise RuntimeError("App layout not configured")
    return layout


def _save_upload_to_inbox(layout: Layout, upload: UploadFile) -> Path:
    base = Path(upload.filename or "upload.bin").name  # strips any path parts
    target_dir = layout.inbox_dir / "uploads"
    ensure_dir(target_dir)

    # Avoid collisions by suffixing if necessary.
    candidate = target_dir / base
    if candidate.exists():
        stem = candidate.stem
        suffix = candidate.suffix
        i = 1
        while True:
            c = target_dir / f"{stem}.{i}{suffix}"
            if not c.exists():
                candidate = c
                break
            i += 1

    with candidate.open("wb") as f:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    return candidate


def _api_key_from_request(request: Request) -> str:
    header_key = request.headers.get("x-api-key")
    if header_key:
        return header_key.strip()
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _is_local_client(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    if host in ("127.0.0.1", "::1", "localhost", "testclient"):
        return True
    if host.startswith("127."):
        return True
    return False


def _import_csv_from_path(
    layout: Layout,
    path: str,
    *,
    commit: bool,
    copy_into_sources: bool,
    encoding: str,
    currency: str,
    date_format: str | None,
    day_first: bool,
    sample: int,
    max_rows: int | None,
    mapping_args: dict[str, Any],
) -> dict[str, Any]:
    # Register the source file (idempotent by sha256).
    doc = register_file(
        layout.sources_dir,
        layout.sources_index_path,
        path,
        copy_into_sources=copy_into_sources,
        source_type="bank_csv",
    )
    doc_id = doc["docId"]

    headers, rows = read_csv_rows(path, encoding=encoding)

    if mapping_args.get("date_col"):
        mapping = CsvMapping(
            date_col=mapping_args.get("date_col"),
            description_col=mapping_args.get("description_col"),
            amount_col=mapping_args.get("amount_col"),
            debit_col=mapping_args.get("debit_col"),
            credit_col=mapping_args.get("credit_col"),
            currency_col=mapping_args.get("currency_col"),
        )
        if not mapping.amount_col and not (mapping.debit_col or mapping.credit_col):
            raise HTTPException(status_code=400, detail="Provide amount_col or debit_col/credit_col.")
    else:
        mapping = infer_mapping(headers)

    imported = 0
    skipped = 0
    errors = 0
    samples: list[dict[str, Any]] = []

    maxn = max_rows if max_rows is not None else len(rows)
    for i, row in enumerate(rows[:maxn], start=1):
        try:
            tx = csv_row_to_tx(
                doc_id=doc_id,
                row_index=i,
                row=row,
                mapping=mapping,
                default_currency=currency,
                date_format=date_format,
                day_first=day_first,
            )
        except Exception:
            errors += 1
            continue

        if commit:
            h = tx["source"]["sourceHash"]
            if has_source_hash(layout, doc_id=doc_id, source_hash=h):
                skipped += 1
                continue
            append_jsonl(layout.transactions_path, tx)
            imported += 1
        else:
            if len(samples) < sample:
                samples.append(tx)

    return {
        "mode": "commit" if commit else "dry-run",
        "docId": doc_id,
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "sample": samples,
    }


def create_app(data_dir: str | None = None) -> FastAPI:
    data_dir = data_dir or os.environ.get("LEDGERFLOW_DATA_DIR") or "data"
    app = FastAPI(title="LedgerFlow", version=__version__)

    layout = layout_for(data_dir)
    app.state.layout = layout
    api_key = os.environ.get("LEDGERFLOW_API_KEY") or ""
    app.state.api_key_required = bool(api_key)
    app.state.auth_mode = "api_key" if api_key else "local_only_no_key"

    # Ensure directories exist, but do not write defaults automatically.
    init_data_layout(layout, write_defaults=False)

    @app.middleware("http")
    async def auth_and_audit_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        method = request.method.upper()
        is_api = path.startswith("/api/")
        is_local = _is_local_client(request)
        requires_auth = bool(api_key) and is_api and (path != "/api/health") and (method != "OPTIONS")
        denied = False
        deny_reason = None

        if requires_auth:
            presented = _api_key_from_request(request)
            if presented != api_key:
                denied = True
                deny_reason = "missing_or_invalid_api_key"
                response = JSONResponse(status_code=401, content={"detail": "API key required"})
            else:
                response = await call_next(request)
        elif is_api and (path != "/api/health") and (method != "OPTIONS") and not is_local:
            denied = True
            deny_reason = "non_local_client_without_api_key"
            response = JSONResponse(
                status_code=401,
                content={"detail": "Non-local API access requires LEDGERFLOW_API_KEY and request auth header."},
            )
        else:
            response = await call_next(request)

        if is_api and method in ("POST", "PUT", "PATCH", "DELETE"):
            evt = {
                "at": utc_now_iso(),
                "method": method,
                "path": path,
                "query": str(request.url.query or ""),
                "status": int(getattr(response, "status_code", 0) or 0),
                "client": (request.client.host if request.client else None),
                "userAgent": request.headers.get("user-agent"),
                "authRequired": requires_auth,
                "authMode": str(getattr(app.state, "auth_mode", "unknown")),
                "authDenied": denied,
                "authDenyReason": deny_reason,
            }
            try:
                append_jsonl(layout.audit_log_path, evt)
            except Exception:
                pass

        return response

    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        def root() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    @app.get("/api/health")
    def health(request: Request) -> dict[str, Any]:
        layout = _get_layout(request)
        return {
            "status": "ok",
            "version": __version__,
            "dataDir": str(layout.data_dir),
            "authEnabled": bool(getattr(request.app.state, "api_key_required", False)),
            "authMode": str(getattr(request.app.state, "auth_mode", "unknown")),
        }

    @app.get("/api/ocr/capabilities")
    def api_ocr_capabilities() -> dict[str, Any]:
        return ocr_capabilities()

    @app.post("/api/ocr/extract-upload")
    def api_ocr_extract_upload(
        request: Request,
        file: UploadFile = File(...),
        image_provider: str = Form(default="auto"),
        preprocess: bool = Form(default=True),
    ) -> dict[str, Any]:
        layout = _get_layout(request)
        saved = _save_upload_to_inbox(layout, file)
        try:
            text, meta = extract_text(saved, image_provider=str(image_provider), preprocess=bool(preprocess))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"savedPath": str(saved), "meta": meta, "text": text}

    @app.post("/api/ocr/extract-path")
    def api_ocr_extract_path(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        _ = _get_layout(request)
        path = str(payload.get("path") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="path is required")
        try:
            text, meta = extract_text(
                path,
                image_provider=str(payload.get("imageProvider") or "auto"),
                preprocess=bool(payload.get("preprocess") if "preprocess" in payload else True),
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"path": path, "meta": meta, "text": text}

    @app.post("/api/init")
    def api_init(request: Request, write_defaults: bool = Body(default=False)) -> dict[str, Any]:
        layout = _get_layout(request)
        init_data_layout(layout, write_defaults=bool(write_defaults))
        return {"ok": True, "dataDir": str(layout.data_dir)}

    @app.post("/api/index/rebuild")
    def api_index_rebuild(request: Request) -> dict[str, Any]:
        layout = _get_layout(request)
        return rebuild_index(layout)

    @app.get("/api/index/stats")
    def api_index_stats(request: Request) -> dict[str, Any]:
        layout = _get_layout(request)
        return index_stats(layout)

    @app.get("/api/migrate/status")
    def api_migrate_status(request: Request) -> dict[str, Any]:
        layout = _get_layout(request)
        return migration_status(layout)

    @app.post("/api/migrate/up")
    def api_migrate_up(request: Request, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        layout = _get_layout(request)
        target = int(payload.get("to") or APP_SCHEMA_VERSION)
        return migrate_to_latest(layout, target_version=target)

    @app.get("/api/transactions")
    def api_transactions(request: Request, limit: int = 50) -> dict[str, Any]:
        layout = _get_layout(request)
        items = recent_transactions(layout, limit=limit, include_deleted=False)
        return {"items": items}

    @app.get("/api/corrections")
    def api_corrections(request: Request, limit: int = 50) -> dict[str, Any]:
        layout = _get_layout(request)
        items = read_jsonl(layout.corrections_path, limit=limit)
        return {"items": items}

    @app.get("/api/sources")
    def api_sources(request: Request, limit: int = 200) -> dict[str, Any]:
        layout = _get_layout(request)
        idx = read_json(layout.sources_index_path, {"version": 1, "docs": []})
        docs = idx.get("docs", [])
        if isinstance(docs, list) and limit is not None and limit >= 0:
            docs = docs[-limit:]
        return {"index": {"version": idx.get("version", 1), "docs": docs}}

    @app.get("/api/review/queue")
    def api_review_queue(request: Request, date: str | None = None, limit: int = 200) -> dict[str, Any]:
        layout = _get_layout(request)
        try:
            return review_queue(layout, date=date, limit=limit)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/review/resolve")
    def api_review_resolve(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        layout = _get_layout(request)
        tx_id = str(payload.get("txId") or "").strip()
        patch = payload.get("patch")
        reason = str(payload.get("reason") or "review_resolve")
        if not tx_id:
            raise HTTPException(status_code=400, detail="txId is required")
        if not isinstance(patch, dict) or not patch:
            raise HTTPException(status_code=400, detail="patch is required")
        try:
            evt = resolve_review_transaction(layout, tx_id=tx_id, patch=patch, reason=reason)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"event": evt}

    @app.post("/api/build")
    def api_build(request: Request, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        layout = _get_layout(request)
        summary = build_daily_monthly_caches(
            layout,
            from_date=payload.get("fromDate"),
            to_date=payload.get("toDate"),
            include_deleted=bool(payload.get("includeDeleted") or False),
        )
        return {"summary": summary}

    @app.post("/api/report/daily")
    def api_report_daily(request: Request, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        layout = _get_layout(request)
        date = str(payload.get("date") or today_ymd())
        parse_ymd(date)
        paths = write_daily_report(layout, date=date)
        return {"date": date, "paths": paths}

    @app.get("/api/report/daily/{ymd}")
    def api_report_daily_get(request: Request, ymd: str) -> PlainTextResponse:
        layout = _get_layout(request)
        parse_ymd(ymd)
        p = layout.reports_dir / "daily" / f"{ymd}.md"
        if not p.exists():
            raise HTTPException(status_code=404, detail="daily report not found")
        return PlainTextResponse(p.read_text(encoding="utf-8"))

    @app.post("/api/report/monthly")
    def api_report_monthly(request: Request, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        layout = _get_layout(request)
        month = str(payload.get("month") or "").strip()
        if not month or len(month) != 7 or month[4] != "-":
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
        paths = write_monthly_report(layout, month=month)
        return {"month": month, "paths": paths}

    @app.get("/api/report/monthly/{month}")
    def api_report_monthly_get(request: Request, month: str) -> PlainTextResponse:
        layout = _get_layout(request)
        if not month or len(month) != 7 or month[4] != "-":
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
        p = layout.reports_dir / "monthly" / f"{month}.md"
        if not p.exists():
            raise HTTPException(status_code=404, detail="monthly report not found")
        return PlainTextResponse(p.read_text(encoding="utf-8"))

    @app.post("/api/charts/series")
    def api_charts_series(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        layout = _get_layout(request)
        from_date = str(payload.get("fromDate") or "")
        to_date = str(payload.get("toDate") or "")
        parse_ymd(from_date)
        parse_ymd(to_date)
        data = build_series(layout, from_date=from_date, to_date=to_date)
        return {"data": data}

    @app.post("/api/charts/month")
    def api_charts_month(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        layout = _get_layout(request)
        month = str(payload.get("month") or "").strip()
        if not month or len(month) != 7 or month[4] != "-":
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
        data1 = build_category_breakdown_month(layout, month=month)
        data2 = build_merchant_top_month(layout, month=month, limit=int(payload.get("limit") or 25))
        return {"categoryBreakdown": data1, "merchantTop": data2}

    @app.post("/api/alerts/run")
    def api_alerts_run(request: Request, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        layout = _get_layout(request)
        at = str(payload.get("at") or today_ymd())
        parse_ymd(at)
        res = run_alerts(layout, at_date=at, commit=bool(payload.get("commit") if "commit" in payload else True))
        return res

    @app.get("/api/alerts/events")
    def api_alerts_events(request: Request, limit: int = 50) -> dict[str, Any]:
        layout = _get_layout(request)
        items = read_jsonl(layout.alerts_dir / "events.jsonl", limit=limit)
        return {"items": items}

    @app.get("/api/audit/events")
    def api_audit_events(request: Request, limit: int = 100) -> dict[str, Any]:
        layout = _get_layout(request)
        items = read_jsonl(layout.audit_log_path, limit=limit)
        return {"items": items}

    @app.post("/api/export/csv")
    def api_export_csv(request: Request, payload: dict[str, Any] = Body(default={})) -> FileResponse:
        layout = _get_layout(request)
        out_dir = layout.data_dir / "exports"
        ensure_dir(out_dir)
        out_path = out_dir / "transactions.csv"
        export_transactions_csv(
            layout,
            out_path=out_path,
            from_date=payload.get("fromDate"),
            to_date=payload.get("toDate"),
            include_deleted=bool(payload.get("includeDeleted") or False),
        )
        return FileResponse(out_path, media_type="text/csv", filename="transactions.csv")

    @app.post("/api/manual/add")
    def api_manual_add(
        request: Request,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        layout = _get_layout(request)

        occurred_at = payload.get("occurredAt") or today_ymd()
        parse_ymd(occurred_at)

        amount = payload.get("amount") or {}
        amount_value = parse_amount(str(amount.get("value")))
        currency = str(amount.get("currency") or "USD")

        merchant = str(payload.get("merchant") or "").strip()
        if not merchant:
            raise HTTPException(status_code=400, detail="merchant is required")

        entry = ManualEntry(
            occurred_at=occurred_at,
            amount_value=amount_value,
            currency=currency,
            merchant=merchant,
            description=(payload.get("description") or None),
            category_hint=(payload.get("categoryHint") or None),
            tags=list(payload.get("tags") or []),
            receipt_doc_id=(payload.get("links") or {}).get("receiptDocId"),
            bill_doc_id=(payload.get("links") or {}).get("billDocId"),
        )
        tx = manual_entry_to_tx(entry)
        append_jsonl(layout.transactions_path, tx)
        return {"tx": tx}

    @app.post("/api/manual/edit")
    def api_manual_edit(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        layout = _get_layout(request)

        tx_id = str(payload.get("txId") or "").strip()
        if not tx_id:
            raise HTTPException(status_code=400, detail="txId is required")

        patch = payload.get("patch") or {}
        if not isinstance(patch, dict) or not patch:
            raise HTTPException(status_code=400, detail="patch is required")

        if "occurredAt" in patch:
            parse_ymd(str(patch["occurredAt"]))

        evt = correction_event(tx_id, patch=patch, reason=str(payload.get("reason") or "user_override"))
        append_jsonl(layout.corrections_path, evt)
        return {"event": evt}

    @app.post("/api/manual/delete")
    def api_manual_delete(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        layout = _get_layout(request)
        tx_id = str(payload.get("txId") or "").strip()
        if not tx_id:
            raise HTTPException(status_code=400, detail="txId is required")
        evt = tombstone_event(tx_id, reason=str(payload.get("reason") or "user_delete"))
        append_jsonl(layout.corrections_path, evt)
        return {"event": evt}

    @app.post("/api/manual/bulk-add")
    def api_manual_bulk_add(request: Request, payload: list[dict[str, Any]] = Body(...)) -> dict[str, Any]:
        layout = _get_layout(request)
        created = 0
        tx_ids: list[str] = []
        for obj in payload:
            if not isinstance(obj, dict):
                continue
            occurred_at = obj.get("occurredAt") or today_ymd()
            parse_ymd(str(occurred_at))

            amount = obj.get("amount") or {}
            if not isinstance(amount, dict):
                continue
            amount_value = parse_amount(str(amount.get("value")))
            currency = str(amount.get("currency") or "USD")

            merchant = str(obj.get("merchant") or "").strip()
            if not merchant:
                continue

            entry = ManualEntry(
                occurred_at=str(occurred_at),
                amount_value=amount_value,
                currency=currency,
                merchant=merchant,
                description=(obj.get("description") or None),
                category_hint=(obj.get("categoryHint") or None),
                tags=list(obj.get("tags") or []),
                receipt_doc_id=(obj.get("links") or {}).get("receiptDocId") if isinstance(obj.get("links"), dict) else None,
                bill_doc_id=(obj.get("links") or {}).get("billDocId") if isinstance(obj.get("links"), dict) else None,
            )
            tx = manual_entry_to_tx(entry)
            append_jsonl(layout.transactions_path, tx)
            created += 1
            tx_ids.append(str(tx.get("txId")))

        return {"created": created, "txIds": tx_ids}

    @app.post("/api/sources/register-upload")
    def api_sources_register_upload(
        request: Request,
        file: UploadFile = File(...),
        copy_into_sources: bool = Form(default=False),
        source_type: str | None = Form(default=None),
    ) -> dict[str, Any]:
        layout = _get_layout(request)
        saved = _save_upload_to_inbox(layout, file)
        doc = register_file(
            layout.sources_dir,
            layout.sources_index_path,
            saved,
            copy_into_sources=bool(copy_into_sources),
            source_type=str(source_type) if source_type else None,
        )
        return {"doc": doc, "savedPath": str(saved)}

    @app.post("/api/import/csv-upload")
    def api_import_csv_upload(
        request: Request,
        file: UploadFile = File(...),
        commit: bool = Form(default=False),
        copy_into_sources: bool = Form(default=False),
        encoding: str = Form(default="utf-8-sig"),
        currency: str = Form(default="USD"),
        date_format: str | None = Form(default=None),
        day_first: bool = Form(default=False),
        sample: int = Form(default=5),
        max_rows: int | None = Form(default=None),
        # Explicit mapping (optional):
        date_col: str | None = Form(default=None),
        description_col: str | None = Form(default=None),
        amount_col: str | None = Form(default=None),
        debit_col: str | None = Form(default=None),
        credit_col: str | None = Form(default=None),
        currency_col: str | None = Form(default=None),
    ) -> JSONResponse:
        layout = _get_layout(request)
        saved = _save_upload_to_inbox(layout, file)

        result = _import_csv_from_path(
            layout,
            str(saved),
            commit=bool(commit),
            copy_into_sources=bool(copy_into_sources),
            encoding=str(encoding),
            currency=str(currency),
            date_format=str(date_format) if date_format else None,
            day_first=bool(day_first),
            sample=int(sample),
            max_rows=int(max_rows) if max_rows is not None else None,
            mapping_args={
                "date_col": date_col,
                "description_col": description_col,
                "amount_col": amount_col,
                "debit_col": debit_col,
                "credit_col": credit_col,
                "currency_col": currency_col,
            },
        )
        result["savedPath"] = str(saved)
        return JSONResponse(result)

    @app.post("/api/import/receipt-upload")
    def api_import_receipt_upload(
        request: Request,
        file: UploadFile = File(...),
        currency: str = Form(default="USD"),
        copy_into_sources: bool = Form(default=False),
        image_provider: str = Form(default="auto"),
        preprocess: bool = Form(default=True),
    ) -> JSONResponse:
        layout = _get_layout(request)
        saved = _save_upload_to_inbox(layout, file)
        try:
            res = import_and_parse_receipt(
                layout,
                saved,
                copy_into_sources=bool(copy_into_sources),
                default_currency=str(currency),
                image_provider=str(image_provider),
                preprocess=bool(preprocess),
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return JSONResponse({"docId": res["doc"]["docId"], "parse": res["parse"], "savedPath": str(saved)})

    @app.post("/api/import/bill-upload")
    def api_import_bill_upload(
        request: Request,
        file: UploadFile = File(...),
        currency: str = Form(default="USD"),
        copy_into_sources: bool = Form(default=False),
        image_provider: str = Form(default="auto"),
        preprocess: bool = Form(default=True),
    ) -> JSONResponse:
        layout = _get_layout(request)
        saved = _save_upload_to_inbox(layout, file)
        try:
            res = import_and_parse_bill(
                layout,
                saved,
                copy_into_sources=bool(copy_into_sources),
                default_currency=str(currency),
                image_provider=str(image_provider),
                preprocess=bool(preprocess),
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return JSONResponse({"docId": res["doc"]["docId"], "parse": res["parse"], "savedPath": str(saved)})

    @app.post("/api/link/receipts")
    def api_link_receipts(request: Request, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        layout = _get_layout(request)
        return link_receipts_to_bank(
            layout,
            max_days_diff=int(payload.get("maxDaysDiff") or 3),
            amount_tolerance=str(payload.get("amountTolerance") or "0.01"),
            commit=bool(payload.get("commit") if "commit" in payload else True),
        )

    @app.post("/api/link/bills")
    def api_link_bills(request: Request, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        layout = _get_layout(request)
        return link_bills_to_bank(
            layout,
            max_days_diff=int(payload.get("maxDaysDiff") or 7),
            amount_tolerance=str(payload.get("amountTolerance") or "0.01"),
            commit=bool(payload.get("commit") if "commit" in payload else True),
        )

    @app.post("/api/dedup/manual-vs-bank")
    def api_dedup_manual_vs_bank(request: Request, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        layout = _get_layout(request)
        return mark_manual_duplicates_against_bank(
            layout,
            from_date=payload.get("fromDate"),
            to_date=payload.get("toDate"),
            max_days_diff=int(payload.get("maxDaysDiff") or 1),
            amount_tolerance=str(payload.get("amountTolerance") or "0.01"),
            commit=bool(payload.get("commit") if "commit" in payload else True),
        )

    @app.post("/api/import/csv-path")
    def api_import_csv_path(request: Request, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        layout = _get_layout(request)
        path = str(payload.get("path") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="path is required")

        result = _import_csv_from_path(
            layout,
            path,
            commit=bool(payload.get("commit") or False),
            copy_into_sources=bool(payload.get("copyIntoSources") or False),
            encoding=str(payload.get("encoding") or "utf-8-sig"),
            currency=str(payload.get("currency") or "USD"),
            date_format=(str(payload["dateFormat"]) if payload.get("dateFormat") else None),
            day_first=bool(payload.get("dayFirst") or False),
            sample=int(payload.get("sample") or 5),
            max_rows=(int(payload["maxRows"]) if payload.get("maxRows") is not None else None),
            mapping_args={
                "date_col": payload.get("dateCol"),
                "description_col": payload.get("descriptionCol"),
                "amount_col": payload.get("amountCol"),
                "debit_col": payload.get("debitCol"),
                "credit_col": payload.get("creditCol"),
                "currency_col": payload.get("currencyCol"),
            },
        )
        return JSONResponse(result)

    return app
