# CLI

LedgerFlow’s CLI is currently run as a Python module:

```bash
python3 -m ledgerflow --help
```

Global flag:

- `--data-dir`: where LedgerFlow reads/writes the local dataset (default: `./data`)

## Initialize Data Layout

```bash
python3 -m ledgerflow init
python3 -m ledgerflow --data-dir /absolute/path/to/data init
```

Optional:

- `--no-defaults`: do not write starter config files (`data/rules/categories.json`, `data/alerts/alert_rules.json`)

## Manual Transactions (Append-Only)

Add a transaction:

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

Write a correction event (does not rewrite the original tx line):

```bash
python3 -m ledgerflow manual edit \
  --tx-id tx_... \
  --set-category restaurants \
  --reason user_override
```

Tombstone (delete) a tx (append-only correction event):

```bash
python3 -m ledgerflow manual delete --tx-id tx_...
```

Bulk add from a JSON array (file or stdin):

```bash
python3 -m ledgerflow manual bulk-add --file entries.json
```

## Source Registry (Hashing + Index)

Register files idempotently by `sha256` into `data/sources/index.json`:

```bash
python3 -m ledgerflow sources register data/inbox/bank/statement.csv
```

Optional:

- `--copy`: copy the file into `data/sources/<docId>/original.<ext>`
- `--source-type`: annotate source type (for example `bank_csv`, `receipt`, `bill`)

## OCR Utilities

Capability check:

```bash
python3 -m ledgerflow ocr doctor
```

Extract text directly:

```bash
python3 -m ledgerflow ocr extract data/inbox/receipts/receipt.jpg
python3 -m ledgerflow ocr extract data/inbox/bills/invoice.pdf --json
python3 -m ledgerflow ocr extract data/inbox/receipts/receipt.jpg --image-provider tesseract --no-preprocess
```

Image OCR controls:

- `--image-provider auto|pytesseract|tesseract|openai` (default `auto`)
- `--no-preprocess` disables variant scoring (`gray/auto/bw/upscaled`)

## Import Bank CSV

Dry-run (prints a sample of normalized transactions):

```bash
python3 -m ledgerflow import csv data/inbox/bank/statement.csv --sample 5
```

Commit import (writes new transactions to `data/ledger/transactions.jsonl`, dedups by `source.sourceHash` for the same `docId`):

```bash
python3 -m ledgerflow import csv data/inbox/bank/statement.csv --commit
```

If inference fails (unknown headers), provide explicit mapping:

```bash
python3 -m ledgerflow import csv data/inbox/bank/statement.csv \
  --commit \
  --date-col "Transaction Date" \
  --description-col "Description" \
  --amount-col "Amount" \
  --currency-col "Currency"
```

Date parsing:

- Use `--date-format` (recommended if your CSV uses `MM/DD/YYYY` or other ambiguous formats)
- Or set `--day-first` for `DD/MM/YYYY` when guessing slash dates

## Import Receipts / Bills

Import + parse a receipt (supports `*.txt` out of the box; `*.pdf`/images require optional dependencies in `requirements.txt`):

```bash
python3 -m ledgerflow import receipt data/inbox/receipts/receipt.txt --currency USD
python3 -m ledgerflow import receipt data/inbox/receipts/receipt.jpg --image-provider openai
```

Import + parse a bill/invoice:

```bash
python3 -m ledgerflow import bill data/inbox/bills/invoice.txt --currency USD
```

`import receipt` / `import bill` also accept:

- `--image-provider auto|pytesseract|tesseract|openai`
- `--no-preprocess`

## Auto-Link Receipts To Bank Transactions

This writes `CorrectionEvents` into `data/ledger/corrections.jsonl`.

Dry-run:

```bash
python3 -m ledgerflow link receipts --dry-run
```

Commit:

```bash
python3 -m ledgerflow link receipts
```

Link bills (best-effort) to bank transactions:

```bash
python3 -m ledgerflow link bills
```

Tuning:

- `--max-days-diff` (receipts default `3`, bills default `7`)
- `--amount-tolerance` (default `0.01`)

## Build Derived Caches

Build deterministic daily/monthly cache files under `data/ledger/daily/` and `data/ledger/monthly/`:

```bash
python3 -m ledgerflow build
```

Range-limited build:

```bash
python3 -m ledgerflow build --from-date 2026-02-01 --to-date 2026-02-29
```

## SQLite Index

Show index stats:

```bash
python3 -m ledgerflow index stats
```

Rebuild index from source-of-truth files:

```bash
python3 -m ledgerflow index rebuild
```

## Migrations

Status:

```bash
python3 -m ledgerflow migrate status
```

Apply to latest:

```bash
python3 -m ledgerflow migrate up
```

## Reports

Daily report:

```bash
python3 -m ledgerflow report daily --date 2026-02-10
```

Monthly report:

```bash
python3 -m ledgerflow report monthly --month 2026-02
```

## Charts

Time series (day granularity):

```bash
python3 -m ledgerflow charts series --from-date 2026-02-01 --to-date 2026-02-29
```

Monthly breakdown datasets:

```bash
python3 -m ledgerflow charts month --month 2026-02
```

## Alerts

Run alerts for a date (default: today). This reads `data/alerts/alert_rules.json` and writes:

- `data/alerts/events.jsonl`
- `data/alerts/state.json`

```bash
python3 -m ledgerflow alerts run --at 2026-02-10
```

Dry-run (no writes):

```bash
python3 -m ledgerflow alerts run --at 2026-02-10 --dry-run
```

## Export

Export corrected transactions to CSV:

```bash
python3 -m ledgerflow export csv --out data/exports/transactions.csv
```

## Dedup / Reconciliation

Mark manual transactions that likely duplicate bank transactions (writes CorrectionEvents unless `--dry-run`):

```bash
python3 -m ledgerflow dedup manual-vs-bank --dry-run
python3 -m ledgerflow dedup manual-vs-bank
```

## Run Webapp + API Server

```bash
python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```

Dev-only:

- `--reload` enables auto-reload
