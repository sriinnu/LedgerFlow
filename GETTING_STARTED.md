# Getting Started (LedgerFlow)

LedgerFlow is a local-first pipeline for tracking money from bank CSVs, bills, receipts, and manual entries.

This guide gets you from zero to a working ledger with reports, alerts, and web UI.

## 1) Install

```bash
cd /Users/srinivaspendela/Sriinnu/Personal/Ledgerflow
python3 -m pip install -r requirements.txt
```

## 2) Initialize Data Layout

```bash
python3 -m ledgerflow init
```

Optional custom data directory:

```bash
python3 -m ledgerflow --data-dir /absolute/path/to/my-ledger-data init
```

## 3) Place Inputs

Recommended folders:

- `data/inbox/bank/` for CSV exports
- `data/inbox/receipts/` for receipts
- `data/inbox/bills/` for bills/invoices

## 4) Import Transactions

### Bank CSV

```bash
# Dry-run sample
python3 -m ledgerflow import csv data/inbox/bank/statement.csv --sample 5

# Commit to ledger
python3 -m ledgerflow import csv data/inbox/bank/statement.csv --commit
```

### Receipt / Bill

```bash
python3 -m ledgerflow import receipt data/inbox/receipts/receipt.jpg --currency USD
python3 -m ledgerflow import bill data/inbox/bills/invoice.pdf --currency USD
```

### Manual Entry

```bash
python3 -m ledgerflow manual add \
  --occurred-at 2026-02-10 \
  --amount -12.30 \
  --currency USD \
  --merchant "Farmers Market" \
  --description "cash vegetables" \
  --category-hint groceries \
  --tags cash
```

## 5) Build + Analyze

```bash
python3 -m ledgerflow build
python3 -m ledgerflow report daily --date 2026-02-10
python3 -m ledgerflow report monthly --month 2026-02
python3 -m ledgerflow charts series --from-date 2026-02-01 --to-date 2026-02-29
python3 -m ledgerflow charts month --month 2026-02
python3 -m ledgerflow alerts run --at 2026-02-10
```

## 6) Review Queue + Resolution

```bash
# Show flagged items (low confidence, uncategorized, duplicates, low parse confidence)
python3 -m ledgerflow review queue --date 2026-02-10 --limit 100

# Resolve by writing a correction event
python3 -m ledgerflow review resolve --tx-id tx_... --set-category groceries
```

## 7) Run Web + API

```bash
python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```

- Web UI: http://127.0.0.1:8787/
- API docs: http://127.0.0.1:8787/docs

Optional API key protection:

```bash
LEDGERFLOW_API_KEY=change-me python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```

By default (no key), API access is local-only. Non-local API calls are denied.
When key mode is enabled, use `X-API-Key` or `Authorization: Bearer` for API requests.

## 8) OCR Notes

```bash
python3 -m ledgerflow ocr doctor
python3 -m ledgerflow ocr extract data/inbox/receipts/receipt.jpg --json
python3 -m ledgerflow ocr extract data/inbox/receipts/receipt.jpg --image-provider tesseract --no-preprocess
```

OpenAI OCR fallback requires:

- `OPENAI_API_KEY` environment variable
- `openai` package installed

## 9) Validate Setup

```bash
python3 -m unittest discover -s tests
```

## 10) Core Principles

- `transactions.jsonl` is append-only.
- User/system edits are `CorrectionEvents` in `corrections.jsonl`.
- Reports/charts are deterministic rebuild outputs.
- Keep raw financial data under `data/` private (already gitignored).

## 11) Fast Demo (Included Samples)

```bash
./scripts/demo_onboarding.sh
```

This runs a complete import/build/report/charts/alerts/review flow against bundled sample files in `samples/`.
