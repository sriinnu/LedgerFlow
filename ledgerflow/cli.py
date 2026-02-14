from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ai_analysis import analyze_spending
from .automation import dispatch_due_and_work, enqueue_due_jobs, enqueue_task, list_dead_letters, list_tasks, queue_stats, read_jobs, run_next_task, run_worker, write_jobs
from .backup import create_backup, restore_backup
from .extraction import extract_text, ocr_capabilities
from .bootstrap import init_data_layout
from .building import build_daily_monthly_caches
from .csv_import import CsvMapping, csv_row_to_tx, infer_mapping, read_csv_rows
from .exporting import export_transactions_csv
from .integration_bank_json import import_bank_json_path
from .index_db import has_source_hash, index_stats, rebuild_index
from .layout import layout_for
from .manual import ManualEntry, correction_event, manual_entry_to_tx, parse_amount, tombstone_event
from .migrations import APP_SCHEMA_VERSION, migrate_to_latest, status as migration_status
from .reporting import write_daily_report, write_monthly_report
from .review import resolve_review_transaction, review_queue
from .sources import register_file
from .storage import append_jsonl
from .alerts import run_alerts
from .charts import write_category_breakdown_month, write_merchant_top_month, write_series
from .documents import import_and_parse_bill, import_and_parse_receipt
from .dedup import mark_manual_duplicates_against_bank
from .linking import link_bills_to_bank, link_receipts_to_bank
from .ops import collect_metrics
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


def _cmd_ai_analyze(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    month = args.month or today_ymd()[:7]
    out = analyze_spending(
        layout,
        month=month,
        provider=args.provider,
        model=args.model,
        lookback_months=args.lookback_months,
    )
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
        return 0

    print(out.get("narrative") or "")
    print("")
    print("Insights:")
    for row in out.get("insights") or []:
        print(f"- {row}")
    if out.get("llmError"):
        print("")
        print(f"LLM fallback note: {out['llmError']}")
    return 0


def _cmd_review_queue(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    out = review_queue(layout, date=args.date, limit=args.limit)
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_review_resolve(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    patch: dict[str, object] = {}
    if args.set_category:
        patch["category"] = {"id": args.set_category}
    if args.set_merchant:
        patch["merchant"] = args.set_merchant
    if args.set_occurred_at:
        parse_ymd(args.set_occurred_at)
        patch["occurredAt"] = args.set_occurred_at
    if not patch:
        raise SystemExit("No changes specified. Use --set-category/--set-merchant/--set-occurred-at.")
    evt = resolve_review_transaction(layout, tx_id=args.tx_id, patch=patch, reason=args.reason)
    print(json.dumps({"event": evt}, ensure_ascii=False))
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


def _cmd_import_bank_json(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    mapping = None
    if args.mapping_file:
        raw = json.loads(Path(args.mapping_file).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise SystemExit("mapping file must contain a JSON object")
        mapping = {str(k): str(v) for k, v in raw.items() if v is not None}
    out = import_bank_json_path(
        layout,
        args.path,
        commit=args.commit,
        copy_into_sources=args.copy_into_sources,
        default_currency=args.currency,
        sample=args.sample,
        max_rows=args.max_rows,
        mapping=mapping,
    )
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_import_receipt(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    res = import_and_parse_receipt(
        layout,
        args.path,
        copy_into_sources=args.copy_into_sources,
        default_currency=args.currency,
        image_provider=args.image_provider,
        preprocess=not args.no_preprocess,
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
        image_provider=args.image_provider,
        preprocess=not args.no_preprocess,
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
    text, meta = extract_text(args.path, image_provider=args.image_provider, preprocess=not args.no_preprocess)
    if args.json:
        print(json.dumps({"path": args.path, "meta": meta, "text": text}, ensure_ascii=False))
    else:
        print(text)
    return 0


def _parse_payload_json(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("payload json must be an object")
    return data


def _cmd_automation_tasks(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    items = list_tasks(layout, limit=args.limit, status=args.status)
    print(json.dumps({"items": items, "count": len(items)}, ensure_ascii=False))
    return 0


def _cmd_automation_stats(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    out = queue_stats(layout)
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_automation_dead_letters(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    items = list_dead_letters(layout, limit=args.limit)
    print(json.dumps({"items": items, "count": len(items)}, ensure_ascii=False))
    return 0


def _cmd_automation_enqueue(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    payload = _parse_payload_json(args.payload_json)
    task = enqueue_task(
        layout,
        task_type=args.task_type,
        payload=payload,
        run_at=args.run_at,
        max_retries=args.max_retries,
        source="cli",
    )
    print(json.dumps({"task": task}, ensure_ascii=False))
    return 0


def _cmd_automation_run_next(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    out = run_next_task(layout, worker_id=args.worker_id)
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_automation_run_due(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    out = enqueue_due_jobs(layout, at=args.at)
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_automation_jobs_list(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    out = read_jobs(layout)
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_automation_jobs_set(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("jobs file must contain a JSON object")
    out = write_jobs(layout, payload)
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_automation_worker(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    out = run_worker(
        layout,
        worker_id=args.worker_id,
        max_tasks=args.max_tasks,
        poll_seconds=args.poll_seconds,
    )
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_automation_dispatch(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    out = dispatch_due_and_work(
        layout,
        run_due=not args.skip_due,
        at=args.at,
        worker_id=args.worker_id,
        max_tasks=args.max_tasks,
        poll_seconds=args.poll_seconds,
    )
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_backup_create(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    out = create_backup(
        layout,
        out_path=args.out,
        include_inbox=not args.no_inbox,
    )
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_backup_restore(args: argparse.Namespace) -> int:
    out = restore_backup(
        args.archive,
        target_dir=args.target_dir,
        force=bool(args.force),
    )
    print(json.dumps(out, ensure_ascii=False))
    return 0


def _cmd_ops_metrics(args: argparse.Namespace) -> int:
    layout = layout_for(args.data_dir)
    init_data_layout(layout, write_defaults=False)
    out = collect_metrics(layout)
    print(json.dumps(out, ensure_ascii=False))
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

    p_ai = sub.add_parser("ai", help="AI-powered spending analysis and narratives.")
    sub_ai = p_ai.add_subparsers(dest="ai_cmd", required=True)

    p_ai_an = sub_ai.add_parser("analyze", help="Analyze spending for a month and return insights.")
    p_ai_an.add_argument("--month", help="YYYY-MM (default: current month)")
    p_ai_an.add_argument(
        "--provider",
        default="auto",
        choices=("auto", "heuristic", "ollama", "openai"),
        help="Narrative provider strategy.",
    )
    p_ai_an.add_argument("--model", help="Optional model override (provider-specific).")
    p_ai_an.add_argument("--lookback-months", type=int, default=6, help="History window including target month.")
    p_ai_an.add_argument("--json", action="store_true", help="Emit full JSON output.")
    p_ai_an.set_defaults(func=_cmd_ai_analyze)

    p_review = sub.add_parser("review", help="Review queue and resolution helpers.")
    sub_review = p_review.add_subparsers(dest="review_cmd", required=True)

    p_rq = sub_review.add_parser("queue", help="List transactions/source parses requiring review.")
    p_rq.add_argument("--date", help="Optional YYYY-MM-DD filter.")
    p_rq.add_argument("--limit", type=int, default=200)
    p_rq.set_defaults(func=_cmd_review_queue)

    p_rr = sub_review.add_parser("resolve", help="Resolve a transaction review item via CorrectionEvent patch.")
    p_rr.add_argument("--tx-id", required=True)
    p_rr.add_argument("--set-category")
    p_rr.add_argument("--set-merchant")
    p_rr.add_argument("--set-occurred-at", help="YYYY-MM-DD")
    p_rr.add_argument("--reason", default="review_resolve")
    p_rr.set_defaults(func=_cmd_review_resolve)

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
    p_ocr_ext.add_argument(
        "--image-provider",
        default="auto",
        choices=("auto", "pytesseract", "tesseract", "openai"),
        help="Image OCR backend (for image files only).",
    )
    p_ocr_ext.add_argument(
        "--no-preprocess",
        action="store_true",
        help="Disable image preprocessing variants for OCR.",
    )
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

    p_ibjson = sub_import.add_parser("bank-json", help="Import transactions from a bank/integration JSON export.")
    p_ibjson.add_argument("path")
    p_ibjson.add_argument("--currency", default="USD", help="Default currency when omitted in rows.")
    p_ibjson.add_argument("--copy-into-sources", action="store_true", help="Copy file into data/sources/<docId>/")
    p_ibjson.add_argument(
        "--commit",
        action="store_true",
        help="Write imported transactions to the ledger (default is dry-run).",
    )
    p_ibjson.add_argument("--sample", type=int, default=5, help="How many txs to print in dry-run mode.")
    p_ibjson.add_argument("--max-rows", type=int, help="Limit number of JSON rows processed.")
    p_ibjson.add_argument(
        "--mapping-file",
        help="Optional JSON mapping file for nested fields (keys: date, amount, currency, merchant, description, category).",
    )
    p_ibjson.set_defaults(func=_cmd_import_bank_json)

    p_irec = sub_import.add_parser("receipt", help="Import + parse a receipt (PDF/image/text).")
    p_irec.add_argument("path")
    p_irec.add_argument("--currency", default="USD", help="Default currency when not detected.")
    p_irec.add_argument("--copy-into-sources", action="store_true")
    p_irec.add_argument(
        "--image-provider",
        default="auto",
        choices=("auto", "pytesseract", "tesseract", "openai"),
        help="Image OCR backend (for image files only).",
    )
    p_irec.add_argument(
        "--no-preprocess",
        action="store_true",
        help="Disable image preprocessing variants for OCR.",
    )
    p_irec.set_defaults(func=_cmd_import_receipt)

    p_ibill = sub_import.add_parser("bill", help="Import + parse a bill/invoice (PDF/text).")
    p_ibill.add_argument("path")
    p_ibill.add_argument("--currency", default="USD", help="Default currency when not detected.")
    p_ibill.add_argument("--copy-into-sources", action="store_true")
    p_ibill.add_argument(
        "--image-provider",
        default="auto",
        choices=("auto", "pytesseract", "tesseract", "openai"),
        help="Image OCR backend (for image files only).",
    )
    p_ibill.add_argument(
        "--no-preprocess",
        action="store_true",
        help="Disable image preprocessing variants for OCR.",
    )
    p_ibill.set_defaults(func=_cmd_import_bill)

    p_serve = sub.add_parser("serve", help="Run the LedgerFlow webapp + API server.")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8787)
    p_serve.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only).")
    p_serve.set_defaults(func=_cmd_serve)

    p_backup = sub.add_parser("backup", help="Create or restore full data backups.")
    sub_backup = p_backup.add_subparsers(dest="backup_cmd", required=True)

    p_bcreate = sub_backup.add_parser("create", help="Create a tar.gz backup from --data-dir.")
    p_bcreate.add_argument("--out", help="Output archive path (default: ../ledgerflow_backups/...).")
    p_bcreate.add_argument("--no-inbox", action="store_true", help="Exclude data/inbox from the backup archive.")
    p_bcreate.set_defaults(func=_cmd_backup_create)

    p_brestore = sub_backup.add_parser("restore", help="Restore a backup archive into a target directory.")
    p_brestore.add_argument("--archive", required=True, help="Path to backup tar.gz.")
    p_brestore.add_argument("--target-dir", required=True, help="Directory where backup will be extracted.")
    p_brestore.add_argument("--force", action="store_true", help="Overwrite non-empty target directory.")
    p_brestore.set_defaults(func=_cmd_backup_restore)

    p_ops = sub.add_parser("ops", help="Operational diagnostics.")
    sub_ops = p_ops.add_subparsers(dest="ops_cmd", required=True)

    p_om = sub_ops.add_parser("metrics", help="Show operational metrics snapshot.")
    p_om.set_defaults(func=_cmd_ops_metrics)

    p_auto = sub.add_parser("automation", help="Automation scheduler + queue operations.")
    sub_auto = p_auto.add_subparsers(dest="automation_cmd", required=True)

    p_atasks = sub_auto.add_parser("tasks", help="List queued/running/completed tasks.")
    p_atasks.add_argument("--limit", type=int, default=100)
    p_atasks.add_argument("--status", help="Comma-separated status filter (queued,running,done,failed).")
    p_atasks.set_defaults(func=_cmd_automation_tasks)

    p_astats = sub_auto.add_parser("stats", help="Queue and dead-letter summary stats.")
    p_astats.set_defaults(func=_cmd_automation_stats)

    p_adl = sub_auto.add_parser("dead-letters", help="List failed tasks from dead-letter log.")
    p_adl.add_argument("--limit", type=int, default=50)
    p_adl.set_defaults(func=_cmd_automation_dead_letters)

    p_aenq = sub_auto.add_parser("enqueue", help="Enqueue a task into the automation queue.")
    p_aenq.add_argument("--task-type", required=True, help="Task type (build, alerts.run, ai.analyze, report.daily, report.monthly).")
    p_aenq.add_argument("--payload-json", help="JSON object payload.")
    p_aenq.add_argument("--run-at", help="ISO timestamp for earliest run time (UTC recommended).")
    p_aenq.add_argument("--max-retries", type=int, default=2)
    p_aenq.set_defaults(func=_cmd_automation_enqueue)

    p_anext = sub_auto.add_parser("run-next", help="Claim and run one queued task.")
    p_anext.add_argument("--worker-id", default="cli-worker")
    p_anext.set_defaults(func=_cmd_automation_run_next)

    p_adue = sub_auto.add_parser("run-due", help="Enqueue due jobs from automation/jobs.json.")
    p_adue.add_argument("--at", help="ISO timestamp override (default: now)")
    p_adue.set_defaults(func=_cmd_automation_run_due)

    p_ajlist = sub_auto.add_parser("jobs-list", help="Print current automation job configuration.")
    p_ajlist.set_defaults(func=_cmd_automation_jobs_list)

    p_ajset = sub_auto.add_parser("jobs-set", help="Replace automation jobs config from JSON file.")
    p_ajset.add_argument("--file", required=True, help="Path to jobs.json payload.")
    p_ajset.set_defaults(func=_cmd_automation_jobs_set)

    p_awrk = sub_auto.add_parser("worker", help="Run worker loop for queued tasks.")
    p_awrk.add_argument("--worker-id", default="cli-worker")
    p_awrk.add_argument("--max-tasks", type=int, default=10)
    p_awrk.add_argument("--poll-seconds", type=float, default=0.2)
    p_awrk.set_defaults(func=_cmd_automation_worker)

    p_adisp = sub_auto.add_parser("dispatch", help="Run scheduler then worker in one command.")
    p_adisp.add_argument("--skip-due", action="store_true", help="Skip due-job enqueue step.")
    p_adisp.add_argument("--at", help="ISO timestamp override for due-job evaluation.")
    p_adisp.add_argument("--worker-id", default="cli-dispatcher")
    p_adisp.add_argument("--max-tasks", type=int, default=10)
    p_adisp.add_argument("--poll-seconds", type=float, default=0.0)
    p_adisp.set_defaults(func=_cmd_automation_dispatch)

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
