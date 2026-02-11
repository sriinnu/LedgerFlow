#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" != "" ]; then
  DATA_DIR="$1"
else
  DATA_DIR="$ROOT/.tmp/demo-$(date +%Y%m%d%H%M%S)"
fi

mkdir -p "$DATA_DIR"

echo "[demo] Using data dir: $DATA_DIR"

echo "[demo] init"
python3 -m ledgerflow --data-dir "$DATA_DIR" init

echo "[demo] import csv"
python3 -m ledgerflow --data-dir "$DATA_DIR" import csv "$ROOT/samples/inbox/bank/statement.csv" --commit --currency USD

echo "[demo] bulk manual add"
python3 -m ledgerflow --data-dir "$DATA_DIR" manual bulk-add --file "$ROOT/samples/manual_entries.json"

echo "[demo] import receipt and bill"
python3 -m ledgerflow --data-dir "$DATA_DIR" import receipt "$ROOT/samples/inbox/receipts/receipt_farmers_market.txt" --currency USD
python3 -m ledgerflow --data-dir "$DATA_DIR" import bill "$ROOT/samples/inbox/bills/invoice_city_power.txt" --currency USD

echo "[demo] link and dedup"
python3 -m ledgerflow --data-dir "$DATA_DIR" link receipts
python3 -m ledgerflow --data-dir "$DATA_DIR" link bills
python3 -m ledgerflow --data-dir "$DATA_DIR" dedup manual-vs-bank

echo "[demo] build/report/charts/alerts/review"
python3 -m ledgerflow --data-dir "$DATA_DIR" build
python3 -m ledgerflow --data-dir "$DATA_DIR" report daily --date 2026-02-10
python3 -m ledgerflow --data-dir "$DATA_DIR" report monthly --month 2026-02
python3 -m ledgerflow --data-dir "$DATA_DIR" charts series --from-date 2026-02-01 --to-date 2026-02-12
python3 -m ledgerflow --data-dir "$DATA_DIR" charts month --month 2026-02
python3 -m ledgerflow --data-dir "$DATA_DIR" alerts run --at 2026-02-10
python3 -m ledgerflow --data-dir "$DATA_DIR" review queue --date 2026-02-10 --limit 50

echo
echo "[demo] Complete. Useful outputs:"
echo "  - $DATA_DIR/reports/daily/2026-02-10.md"
echo "  - $DATA_DIR/reports/monthly/2026-02.md"
echo "  - $DATA_DIR/charts/"
echo "  - $DATA_DIR/alerts/events.jsonl"
echo
echo "[demo] To run web UI on this demo data:"
echo "  python3 -m ledgerflow --data-dir $DATA_DIR serve --host 127.0.0.1 --port 8787"
