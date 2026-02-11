# LedgerFlow

![LedgerFlow Logo](assets/logo.svg)

Local-first money tracking that ingests bank CSVs, bills, receipts, and manual entries into one auditable ledger.

## What It Does

- Append-only ledger:
  - `data/ledger/transactions.jsonl`
  - `data/ledger/corrections.jsonl` (user edits / system link patches)
- Import:
  - bank CSVs (`import csv`)
  - receipts/bills (`import receipt`, `import bill`)
  - manual entries (`manual add`, `manual bulk-add`, `manual edit`, `manual delete`)
- Build + outputs:
  - deterministic daily/monthly caches (`build`)
  - daily/monthly reports (`report daily`, `report monthly`)
  - chart datasets (`charts series`, `charts month`)
  - alerts engine (`alerts run`)
  - CSV export (`export csv`)
- Reconciliation:
  - link receipts and bills to bank transactions
  - mark possible manual-vs-bank duplicates
- API + Web UI:
  - FastAPI docs at `/docs`
  - web UI at `/`

## Quick Start

```bash
cd /Users/srinivaspendela/Sriinnu/Personal/Ledgerflow
python3 -m ledgerflow init

# Import bank CSV
python3 -m ledgerflow import csv data/inbox/bank/statement.csv --commit

# Build derived caches + generate reports/charts/alerts
python3 -m ledgerflow build
python3 -m ledgerflow report daily --date 2026-02-10
python3 -m ledgerflow report monthly --month 2026-02
python3 -m ledgerflow charts series --from-date 2026-02-01 --to-date 2026-02-29
python3 -m ledgerflow alerts run --at 2026-02-10
```

## OCR Through CLI

OCR/text extraction is exposed directly:

```bash
# Capability check (what OCR/PDF backends are available on this machine)
python3 -m ledgerflow ocr doctor

# Extract text from txt/pdf/image
python3 -m ledgerflow ocr extract /path/to/receipt.jpg
python3 -m ledgerflow ocr extract /path/to/bill.pdf --json
```

Receipt and bill imports use OCR/text extraction internally:

```bash
python3 -m ledgerflow import receipt data/inbox/receipts/receipt.jpg
python3 -m ledgerflow import bill data/inbox/bills/invoice.pdf
```

## Run API + Web

```bash
python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```

- Web UI: http://127.0.0.1:8787/
- API docs: http://127.0.0.1:8787/docs

## Docs

- Getting started: `GETTING_STARTED.md`
- CLI: `docs/CLI.md`
- API: `docs/API.md`
- Data layout: `docs/DATA_LAYOUT.md`
- Schemas: `docs/SCHEMAS.md`
- Development: `docs/DEVELOPMENT.md`
- Milestone status: `docs/ROADMAP.md`
- Product spec: `SKILL.md`

## Tests

```bash
python3 -m unittest discover -s tests
```

## Dependencies

Base API/web deps:

```bash
python3 -m pip install -r requirements.txt
```

OCR/PDF notes:

- `*.txt` parsing works without extra system tools
- PDF extraction uses Python libs (`pdfplumber` / `pypdf`) when installed
- Image OCR uses `pytesseract` or system `tesseract` CLI

