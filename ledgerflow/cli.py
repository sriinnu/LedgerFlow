from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .extraction import extract_text, ocr_capabilities
from .bootstrap import init_data_layout
from .building import build_daily_monthly_caches
from .csv_import import CsvMapping, csv_row_to_tx, infer_mapping, read_csv_rows
from .exporting import export_transactions_csv
from .index_db import has_source_hash, index_stats, rebuild_index
from .layout import layout_for
from .manual import ManualEntry, correction_event, manual_entry_to_tx, parse_amount, tombstone_event
from .migrations import APP_SCHEMA_VERSION, migrate_to_latest, status as migration_status
from .reporting import write_daily_report, write_monthly_report
from .sources import register_file
from .storage import append_jsonl
from .alerts import run_alerts
from .charts import write_category_breakdown_month, write_merchant_top_month, write_series
from .documents import import_and_parse_bill, import_and_parse_receipt
from .dedup import mark_manual_duplicates_against_bank
from .linking import link_bills_to_bank, link_receipts_to_bank
from .timeutil import parse_ymd, today_ymd


def _cmd_init(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=not args.no_defaults)
    print(f"Initialized data layout at: {layout.data_dir}")
    return 0


def _cmd_manual_add(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)

    occurred_at = args.occurred_at or today_ymd()
    parse_ymd(occurred_at)

    tags = [t for t in (args.tags.split(",") if args.tags else []) if t]

    entry = ManualEntry(
        occurred_at=occurred_at,
        amount_value=parse_amount(args.amount),
        currency=args.currency,
        merchant=args.merchant,
        description=args.description,
        category_hint=args.category_hint,
        tags=tags,
        receipt_doc_id=args.receipt_doc_id,
        bill_doc_id=args.bill_doc_id,
    )

    tx = manual_entry_to_tx(entry)
    append_jsonl(layout.transactions_path, tx)
    print(tx["txId"])
    return 0


def _cmd_manual_edit(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)

    patch = {}
    if args.set_category:
        patch["category"] = {"id": args.set_category}
    if args.set_merchant:
        patch["merchant"] = args.set_merchant
    if args.set_occurred_at:
        parse_ymd(args.set_occurred_at)
        patch["occurredAt"] = args.set_occurred_at

    if not patch:
        raise SystemExit("No changes specified. Use --set-category/--set-merchant/--set-occurred-at.")

    evt = correction_event(args.tx_id, patch=patch, reason=args.reason)
    append_jsonl(layout.corrections_path, evt)
    print(evt["eventId"])
    return 0


def _cmd_manual_delete(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    evt = tombstone_event(args.tx_id, reason=args.reason)
    append_jsonl(layout.corrections_path, evt)
    print(evt["eventId"])
    return 0


def _cmd_manual_bulk_add(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)

    raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise SystemExit("bulk-add expects a JSON array")

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
        amt_val = parse_amount(str(amount.get("value")))
        currency = str(amount.get("currency") or "USD")
        merchant = str(obj.get("merchant") or "").strip()
        if not merchant:
            continue

        entry = ManualEntry(
            occurred_at=str(occurred_at),
            amount_value=amt_val,
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

    print(json.dumps({"created": created, "txIds": tx_ids}, ensure_ascii=False))
    return 0


def _cmd_sources_register(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)

    for p in args.paths:
        doc = register_file(
            layout.sources_dir,
            layout.sources_index_path,
            p,
            copy_into_sources=args.copy,
            source_type=args.source_type,
        )
        print(json.dumps({"docId": doc["docId"], "sha256": doc["sha256"], "path": doc["originalPath"]}))
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    summary = build_daily_monthly_caches(
        layout,
        from_date=args.from_date,
        to_date=args.to_date,
        include_deleted=args.include_deleted,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def _cmd_index_rebuild(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    result = rebuild_index(layout)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_index_stats(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    print(json.dumps(index_stats(layout), ensure_ascii=False))
    return 0


def _cmd_migrate_status(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    print(json.dumps(migration_status(layout), ensure_ascii=False))
    return 0


def _cmd_migrate_up(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    target = args.to if args.to is not None else APP_SCHEMA_VERSION
    result = migrate_to_latest(layout, target_version=target)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _cmd_report_daily(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    date = args.date or today_ymd()
    parse_ymd(date)
    paths = write_daily_report(layout, date=date)
    print(json.dumps(paths, ensure_ascii=False))
    return 0


def _cmd_report_monthly(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    month = args.month
    if not month or len(month) != 7 or month[4] != "-":
        raise SystemExit("month must be in YYYY-MM format")
    paths = write_monthly_report(layout, month=month)
    print(json.dumps(paths, ensure_ascii=False))
    return 0


def _cmd_charts_series(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    parse_ymd(args.from_date)
    parse_ymd(args.to_date)
    out = write_series(layout, from_date=args.from_date, to_date=args.to_date)
    print(out)
    return 0


def _cmd_charts_month(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    month = args.month
    if not month or len(month) != 7 or month[4] != "-":
        raise SystemExit("month must be in YYYY-MM format")
    out1 = write_category_breakdown_month(layout, month=month)
    out2 = write_merchant_top_month(layout, month=month, limit=args.limit)
    print(json.dumps({"categoryBreakdown": out1, "merchantTop": out2}, ensure_ascii=False))
    return 0


def _cmd_alerts_run(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    at = args.at or today_ymd()
    parse_ymd(at)
    res = run_alerts(layout, at_date=at, commit=not args.dry_run)
    print(json.dumps(res, ensure_ascii=False))
    return 0


def _cmd_export_csv(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    out = export_transactions_csv(
        layout,
        out_path=args.out,
        from_date=args.from_date,
        to_date=args.to_date,
        include_deleted=args.include_deleted,
    )
    print(out)
    return 0


def _cmd_import_csv(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)

    # Register the source file (idempotent by sha256).
    doc = register_file(
        layout.sources_dir,
        layout.sources_index_path,
        args.path,
        copy_into_sources=args.copy_into_sources,
        source_type="bank_csv",
    )
    doc_id = doc["docId"]

    headers, rows = read_csv_rows(args.path, encoding=args.encoding)

    if args.date_col:
        mapping = CsvMapping(
            date_col=args.date_col,
            description_col=args.description_col,
            amount_col=args.amount_col,
            debit_col=args.debit_col,
            credit_col=args.credit_col,
            currency_col=args.currency_col,
        )
        if not mapping.amount_col and not (mapping.debit_col or mapping.credit_col):
            raise SystemExit("Provide --amount-col or --debit-col/--credit-col.")
    else:
        mapping = infer_mapping(headers)

    imported = 0
    skipped = 0
    errors = 0
    printed = 0

    max_rows = args.max_rows if args.max_rows is not None else len(rows)
    for i, row in enumerate(rows[:max_rows], start=1):
        try:
            tx = csv_row_to_tx(
                doc_id=doc_id,
                row_index=i,
                row=row,
                mapping=mapping,
                default_currency=args.currency,
                date_format=args.date_format,
                day_first=args.day_first,
            )
        except Exception as e:
            errors += 1
            if args.verbose_errors:
                print(json.dumps({"row": i, "error": str(e), "raw": row}, ensure_ascii=False))
            continue

        if args.commit:
            h = tx["source"]["sourceHash"]
            if has_source_hash(layout, doc_id=doc_id, source_hash=h):
                skipped += 1
                continue
            append_jsonl(layout.transactions_path, tx)
            imported += 1
        else:
            if printed < args.sample:
                print(json.dumps(tx, ensure_ascii=False))
                printed += 1

    print(
        json.dumps(
            {
                "mode": "commit" if args.commit else "dry-run",
                "docId": doc_id,
                "imported": imported,
                "skipped": skipped,
                "errors": errors,
            }
        )
    )
    return 0


def _cmd_import_receipt(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    res = import_and_parse_receipt(
        layout,
        args.path,
        copy_into_sources=args.copy_into_sources,
        default_currency=args.currency,
    )
    print(json.dumps({"docId": res["doc"]["docId"], "parse": res["parse"]}, ensure_ascii=False))
    return 0


def _cmd_import_bill(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    res = import_and_parse_bill(
        layout,
        args.path,
        copy_into_sources=args.copy_into_sources,
        default_currency=args.currency,
    )
    print(json.dumps({"docId": res["doc"]["docId"], "parse": res["parse"]}, ensure_ascii=False))
    return 0


def _cmd_link_receipts(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    res = link_receipts_to_bank(
        layout,
        max_days_diff=args.max_days_diff,
        amount_tolerance=args.amount_tolerance,
        commit=not args.dry_run,
    )
    print(json.dumps(res, ensure_ascii=False))
    return 0


def _cmd_link_bills(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    res = link_bills_to_bank(
        layout,
        max_days_diff=args.max_days_diff,
        amount_tolerance=args.amount_tolerance,
        commit=not args.dry_run,
    )
    print(json.dumps(res, ensure_ascii=False))
    return 0


def _cmd_dedup_manual_vs_bank(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    res = mark_manual_duplicates_against_bank(
        layout,
        from_date=args.from_date,
        to_date=args.to_date,
        max_days_diff=args.max_days_diff,
        amount_tolerance=args.amount_tolerance,
        commit=not args.dry_run,
    )
    print(json.dumps(res, ensure_ascii=False))
    return 0


def _cmd_ocr_doctor(args: argparse.Namespace) -> int:
    caps = ocr_capabilities()
    print(json.dumps(caps, ensure_ascii=False))
    return 0


def _cmd_ocr_extract(args: argparse.Namespace) -> int:
    text, meta = extract_text(args.path)
    if args.json:
        print(json.dumps({"path": args.path, "meta": meta, "text": text}, ensure_ascii=False))
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ledgerflow", description="LedgerFlow local-first ledger tools.")
    p.add_argument("--data-dir", default="data", help="Data directory (default: ./data)")

    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Initialize data directory layout.")
    p_init.add_argument("--no-defaults", action="store_true", help="Do not write default config files.")
    p_init.set_defaults(func=_cmd_init)

    p_manual = sub.add_parser("manual", help="Manual entries and corrections.")
    sub_manual = p_manual.add_subparsers(dest="manual_cmd", required=True)

    p_madd = sub_manual.add_parser("add", help="Add a manual transaction entry.")
    p_madd.add_argument("--occurred-at", help="YYYY-MM-DD (default: today)")
    p_madd.add_argument("--amount", required=True, help="Amount as decimal string (negative = debit)")
    p_madd.add_argument("--currency", default="USD", help="Currency code (default: USD)")
    p_madd.add_argument("--merchant", required=True)
    p_madd.add_argument("--description")
    p_madd.add_argument("--category-hint")
    p_madd.add_argument("--tags", help="Comma-separated tags (example: cash,work)")
    p_madd.add_argument("--receipt-doc-id")
    p_madd.add_argument("--bill-doc-id")
    p_madd.set_defaults(func=_cmd_manual_add)

    p_medit = sub_manual.add_parser("edit", help="Write a CorrectionEvent for an existing tx.")
    p_medit.add_argument("--tx-id", required=True)
    p_medit.add_argument("--set-category")
    p_medit.add_argument("--set-merchant")
    p_medit.add_argument("--set-occurred-at", help="YYYY-MM-DD")
    p_medit.add_argument("--reason", default="user_override")
    p_medit.set_defaults(func=_cmd_manual_edit)

    p_mdel = sub_manual.add_parser("delete", help="Tombstone a tx (writes a CorrectionEvent).")
    p_mdel.add_argument("--tx-id", required=True)
    p_mdel.add_argument("--reason", default="user_delete")
    p_mdel.set_defaults(func=_cmd_manual_delete)

    p_mbulk = sub_manual.add_parser("bulk-add", help="Add many manual entries from a JSON array.")
    p_mbulk.add_argument("--file", help="Path to JSON file. If omitted, reads stdin.")
    p_mbulk.set_defaults(func=_cmd_manual_bulk_add)

    p_sources = sub.add_parser("sources", help="Document registry (hashing + indexing).")
    sub_sources = p_sources.add_subparsers(dest="sources_cmd", required=True)

    p_sreg = sub_sources.add_parser("register", help="Register one or more files by sha256.")
    p_sreg.add_argument("paths", nargs="+")
    p_sreg.add_argument(
        "--copy",
        action="store_true",
        help="Copy the file into data/sources/<docId>/ as original.<ext>.",
    )
    p_sreg.add_argument("--source-type", help="Optional source type label (example: receipt, bill, bank_csv).")
    p_sreg.set_defaults(func=_cmd_sources_register)

    p_build = sub.add_parser("build", help="Build deterministic derived caches (daily/monthly JSON).")
    p_build.add_argument("--from-date", help="YYYY-MM-DD (inclusive)")
    p_build.add_argument("--to-date", help="YYYY-MM-DD (inclusive)")
    p_build.add_argument("--include-deleted", action="store_true", help="Include tombstoned txs in derived caches.")
    p_build.set_defaults(func=_cmd_build)

    p_index = sub.add_parser("index", help="SQLite index maintenance.")
    sub_index = p_index.add_subparsers(dest="index_cmd", required=True)

    p_ir = sub_index.add_parser("rebuild", help="Rebuild sqlite index from json/jsonl source-of-truth files.")
    p_ir.set_defaults(func=_cmd_index_rebuild)

    p_is = sub_index.add_parser("stats", help="Show sqlite index stats.")
    p_is.set_defaults(func=_cmd_index_stats)

    p_mig = sub.add_parser("migrate", help="App schema migrations.")
    sub_mig = p_mig.add_subparsers(dest="migrate_cmd", required=True)

    p_ms = sub_mig.add_parser("status", help="Show migration status.")
    p_ms.set_defaults(func=_cmd_migrate_status)

    p_mu = sub_mig.add_parser("up", help="Apply migrations up to latest or target version.")
    p_mu.add_argument("--to", type=int, help="Target schema version (default: latest).")
    p_mu.set_defaults(func=_cmd_migrate_up)

    p_report = sub.add_parser("report", help="Generate reports.")
    sub_report = p_report.add_subparsers(dest="report_cmd", required=True)

    p_rday = sub_report.add_parser("daily", help="Generate daily report markdown/json.")
    p_rday.add_argument("--date", help="YYYY-MM-DD (default: today)")
    p_rday.set_defaults(func=_cmd_report_daily)

    p_rmon = sub_report.add_parser("monthly", help="Generate monthly report markdown/json.")
    p_rmon.add_argument("--month", required=True, help="YYYY-MM")
    p_rmon.set_defaults(func=_cmd_report_monthly)

    p_charts = sub.add_parser("charts", help="Generate chart datasets for a UI.")
    sub_charts = p_charts.add_subparsers(dest="charts_cmd", required=True)

    p_cseries = sub_charts.add_parser("series", help="Time series dataset.")
    p_cseries.add_argument("--from-date", required=True, help="YYYY-MM-DD")
    p_cseries.add_argument("--to-date", required=True, help="YYYY-MM-DD")
    p_cseries.set_defaults(func=_cmd_charts_series)

    p_cmonth = sub_charts.add_parser("month", help="Monthly breakdown datasets.")
    p_cmonth.add_argument("--month", required=True, help="YYYY-MM")
    p_cmonth.add_argument("--limit", type=int, default=25, help="Top merchants limit.")
    p_cmonth.set_defaults(func=_cmd_charts_month)

    p_alerts = sub.add_parser("alerts", help="Alerts engine.")
    sub_alerts = p_alerts.add_subparsers(dest="alerts_cmd", required=True)

    p_arun = sub_alerts.add_parser("run", help="Evaluate alert rules for a given date.")
    p_arun.add_argument("--at", help="YYYY-MM-DD (default: today)")
    p_arun.add_argument("--dry-run", action="store_true", help="Do not write events/state.")
    p_arun.set_defaults(func=_cmd_alerts_run)

    p_export = sub.add_parser("export", help="Export ledger data.")
    sub_export = p_export.add_subparsers(dest="export_cmd", required=True)

    p_ecsv = sub_export.add_parser("csv", help="Export corrected transactions to CSV.")
    p_ecsv.add_argument("--out", required=True, help="Output CSV path.")
    p_ecsv.add_argument("--from-date", help="YYYY-MM-DD (inclusive)")
    p_ecsv.add_argument("--to-date", help="YYYY-MM-DD (inclusive)")
    p_ecsv.add_argument("--include-deleted", action="store_true")
    p_ecsv.set_defaults(func=_cmd_export_csv)

    p_link = sub.add_parser("link", help="Link parsed documents to ledger transactions.")
    sub_link = p_link.add_subparsers(dest="link_cmd", required=True)

    p_lrec = sub_link.add_parser("receipts", help="Auto-link receipt docs to bank transactions.")
    p_lrec.add_argument("--max-days-diff", type=int, default=3)
    p_lrec.add_argument("--amount-tolerance", default="0.01")
    p_lrec.add_argument("--dry-run", action="store_true", help="Do not write CorrectionEvents.")
    p_lrec.set_defaults(func=_cmd_link_receipts)

    p_lbill = sub_link.add_parser("bills", help="Auto-link bill docs to bank transactions.")
    p_lbill.add_argument("--max-days-diff", type=int, default=7)
    p_lbill.add_argument("--amount-tolerance", default="0.01")
    p_lbill.add_argument("--dry-run", action="store_true", help="Do not write CorrectionEvents.")
    p_lbill.set_defaults(func=_cmd_link_bills)

    p_dedup = sub.add_parser("dedup", help="Dedup/reconciliation helpers.")
    sub_dedup = p_dedup.add_subparsers(dest="dedup_cmd", required=True)

    p_dm = sub_dedup.add_parser("manual-vs-bank", help="Mark manual txs that likely duplicate bank txs.")
    p_dm.add_argument("--from-date", help="YYYY-MM-DD (inclusive)")
    p_dm.add_argument("--to-date", help="YYYY-MM-DD (inclusive)")
    p_dm.add_argument("--max-days-diff", type=int, default=1)
    p_dm.add_argument("--amount-tolerance", default="0.01")
    p_dm.add_argument("--dry-run", action="store_true")
    p_dm.set_defaults(func=_cmd_dedup_manual_vs_bank)

    p_ocr = sub.add_parser("ocr", help="OCR/text extraction utilities.")
    sub_ocr = p_ocr.add_subparsers(dest="ocr_cmd", required=True)

    p_ocr_doc = sub_ocr.add_parser("doctor", help="Show OCR/PDF extraction capability checks.")
    p_ocr_doc.set_defaults(func=_cmd_ocr_doctor)

    p_ocr_ext = sub_ocr.add_parser("extract", help="Extract text from txt/pdf/image.")
    p_ocr_ext.add_argument("path")
    p_ocr_ext.add_argument("--json", action="store_true", help="Emit JSON with metadata.")
    p_ocr_ext.set_defaults(func=_cmd_ocr_extract)

    p_import = sub.add_parser("import", help="Import sources into the ledger.")
    sub_import = p_import.add_subparsers(dest="import_cmd", required=True)

    p_icsv = sub_import.add_parser("csv", help="Import a bank CSV export.")
    p_icsv.add_argument("path")
    p_icsv.add_argument("--encoding", default="utf-8-sig")
    p_icsv.add_argument("--currency", default="USD", help="Default currency if not present in CSV.")
    p_icsv.add_argument("--date-format", help="strptime format (recommended if your CSV is ambiguous).")
    p_icsv.add_argument("--day-first", action="store_true", help="Prefer DD/MM/YYYY when guessing slash dates.")
    p_icsv.add_argument("--copy-into-sources", action="store_true", help="Copy file into data/sources/<docId>/")
    p_icsv.add_argument(
        "--commit",
        action="store_true",
        help="Write imported transactions to the ledger (default is dry-run).",
    )
    p_icsv.add_argument("--sample", type=int, default=5, help="How many txs to print in dry-run mode.")
    p_icsv.add_argument("--max-rows", type=int, help="Limit number of CSV rows processed.")
    p_icsv.add_argument("--verbose-errors", action="store_true", help="Print row-level errors as JSON lines.")

    # Optional explicit mapping (otherwise inferred by header names).
    p_icsv.add_argument("--date-col", help="CSV column name for date.")
    p_icsv.add_argument("--description-col", help="CSV column name for description/details.")
    p_icsv.add_argument("--amount-col", help="CSV column name for signed amount.")
    p_icsv.add_argument("--debit-col", help="CSV column name for debit amount (positive).")
    p_icsv.add_argument("--credit-col", help="CSV column name for credit amount (positive).")
    p_icsv.add_argument("--currency-col", help="CSV column name for currency.")
    p_icsv.set_defaults(func=_cmd_import_csv)

    p_irec = sub_import.add_parser("receipt", help="Import + parse a receipt (PDF/image/text).")
    p_irec.add_argument("path")
    p_irec.add_argument("--currency", default="USD", help="Default currency when not detected.")
    p_irec.add_argument("--copy-into-sources", action="store_true")
    p_irec.set_defaults(func=_cmd_import_receipt)

    p_ibill = sub_import.add_parser("bill", help="Import + parse a bill/invoice (PDF/text).")
    p_ibill.add_argument("path")
    p_ibill.add_argument("--currency", default="USD", help="Default currency when not detected.")
    p_ibill.add_argument("--copy-into-sources", action="store_true")
    p_ibill.set_defaults(func=_cmd_import_bill)

    p_serve = sub.add_parser("serve", help="Run the LedgerFlow webapp + API server.")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8787)
    p_serve.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only).")
    p_serve.set_defaults(func=_cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def _cmd_serve(args: argparse.Namespace) -> int:
    from .server import create_app

    try:
        import uvicorn
    except Exception as e:  # pragma: no cover
        raise SystemExit(f"uvicorn is required to run the server: {e}")

    app = create_app(args.data_dir)
    uvicorn.run(app, host=args.host, port=args.port, reload=bool(args.reload))
    return 0
