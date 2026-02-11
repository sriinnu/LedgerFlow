# Getting Started (LedgerFlow)

LedgerFlow is a local-first pipeline that turns:

- bank CSV exports
- bills/invoices (PDF)
- receipts (PDF/images)
- manual entries (cash, corrections, splits)

into a single, auditable ledger with daily/monthly reports, alerts, and UI-friendly aggregates.

## 1) Current Repo State

This workspace contains the design/spec (`SKILL.md`) and an MVP-0 Python CLI you can run locally:

- initialize `data/` layout
- add manual transactions (append-only)
- register source documents by sha256 into `data/sources/`

The steps below cover:

- how to initialize a local dataset layout now
- the intended run workflow as the CLI grows (import/build/report/alerts/charts)
- conventions to keep the ledger auditable and safe

## 2) Initialize A Local Dataset

Create the suggested directory layout:

```bash
cd /path/to/Ledgerflow
python3 -m ledgerflow init
```

If you want to keep data elsewhere, use `--data-dir`:

```bash
python3 -m ledgerflow --data-dir /absolute/path/to/ledgerflow-data init
```

The initializer creates the directory layout from `SKILL.md` and writes starter config files (only if missing):

- `data/rules/categories.json`
- `data/alerts/alert_rules.json`

Example `data/rules/categories.json`:

```json
{
  "categories": [
    { "id": "groceries", "label": "Groceries" },
    { "id": "restaurants", "label": "Restaurants" },
    { "id": "rent", "label": "Rent" },
    { "id": "utilities", "label": "Utilities" },
    { "id": "transport", "label": "Transport" },
    { "id": "shopping", "label": "Shopping" },
    { "id": "health", "label": "Health" },
    { "id": "income", "label": "Income" },
    { "id": "uncategorized", "label": "Uncategorized" }
  ]
}
```

Example `data/alerts/alert_rules.json` (from the spec):

```json
{
  "currency": "EUR",
  "rules": [
    { "id": "groceries_monthly", "type": "category_budget", "categoryId": "groceries", "period": "month", "limit": 600 },
    { "id": "restaurants_weekly", "type": "category_budget", "categoryId": "restaurants", "period": "week", "limit": 120 },
    { "id": "new_recurring", "type": "recurring_new", "minOccurrences": 3, "spacingDays": [25, 35] }
  ]
}
```

Note: currency and limits are personal. Set these to whatever matches your accounts (for example `USD`).

## 3) Put Source Documents In `data/inbox/`

Recommended: keep your raw inputs in `data/inbox/` and treat it as append-only.

Typical patterns:

- `data/inbox/bank/` for CSV exports
- `data/inbox/bills/` for invoices/bills
- `data/inbox/receipts/` for receipts (PDF/images)

## 4) Intended Run Workflow (Once Implemented)

The spec describes a small set of core operations:

- `importDocuments`: ingest and parse sources into `data/sources/`
- `buildLedger`: normalize + dedup into append-only `data/ledger/transactions.jsonl`
- `reportDaily` / `reportMonthly`: write Markdown reports
- `charts`: write UI-ready aggregates
- `alerts.run`: evaluate rules and append alert events

Suggested request shapes (from `SKILL.md`):

```json
{ "op": "manual.add", "entry": { "occurredAt": "2026-02-10", "amount": { "value": -12.30, "currency": "EUR" }, "merchant": "Farmers Market", "categoryHint": "groceries" } }
{ "op": "report.daily", "date": "2026-02-10" }
{ "op": "alerts.run", "scope": "now" }
{ "op": "charts", "range": { "from": "2026-02-01", "to": "2026-02-29" }, "granularity": "day" }
```

The current CLI implements this contract (plus OCR/linking/dedup utilities):

- manual entry: `python3 -m ledgerflow manual add ...`
- correction events: `python3 -m ledgerflow manual edit ...`
- doc registry (hashing): `python3 -m ledgerflow sources register ...`
- bank CSV import: `python3 -m ledgerflow import csv ...`
- receipts/bills import (best-effort parsing): `python3 -m ledgerflow import receipt ...`, `python3 -m ledgerflow import bill ...`
- linking receipts to bank txs: `python3 -m ledgerflow link receipts`
- derived caches: `python3 -m ledgerflow build`
- reports: `python3 -m ledgerflow report daily|monthly ...`
- charts: `python3 -m ledgerflow charts series|month ...`
- alerts: `python3 -m ledgerflow alerts run ...`
- export: `python3 -m ledgerflow export csv ...`

## 5) Quickstart (MVP-0/1/2/3)

```bash
# 1) Create the data/ layout
python3 -m ledgerflow init

# 2) Add a manual cash expense
python3 -m ledgerflow manual add \
  --occurred-at 2026-02-10 \
  --amount -12.30 \
  --currency USD \
  --merchant "Farmers Market" \
  --description "cash vegetables" \
  --category-hint groceries \
  --tags cash

# 3) Register a source file (idempotent by sha256)
python3 -m ledgerflow sources register data/inbox/bank/statement.csv

# 4) Import a bank CSV into the ledger (dry-run by default)
python3 -m ledgerflow import csv data/inbox/bank/statement.csv --sample 3

# 5) Commit the import (writes new txs, dedups by sourceHash)
python3 -m ledgerflow import csv data/inbox/bank/statement.csv --commit

# 6) Build derived caches (daily/monthly JSON views)
python3 -m ledgerflow build

# 7) Generate a daily report + charts + alerts
python3 -m ledgerflow report daily --date 2026-02-10
python3 -m ledgerflow charts series --from-date 2026-02-01 --to-date 2026-02-29
python3 -m ledgerflow alerts run --at 2026-02-10
```

## 6) Ledger Conventions (Auditability)

The spec makes a hard design call: do not silently mutate ledger history.

- Append transactions to `data/ledger/transactions.jsonl`
- Record user edits as events in `data/ledger/corrections.jsonl` (CorrectionEvents)
- Rebuild derived views (`daily/`, `monthly/`, reports, charts) deterministically from the append-only sources

Why this matters: you only trust the numbers if you can trace every output back to a source document + deterministic transforms.

## 7) Manual Entries And Corrections

Manual entries are first-class. They should produce transactions with:

- `source.sourceType = "manual"`
- enough metadata to explain why it exists (cash, missing receipt, adjustment)

Edits should never rewrite the original transaction line. Instead, add a correction event that applies as a patch during rebuild.

## 8) Dedup And Idempotency

Ingestion should be idempotent:

- importing the same file twice must not duplicate ledger entries
- if a bank transaction matches a manual transaction (same amount, close date, similar merchant), prefer bank as canonical and flag the manual tx as `duplicate_candidate` for review

## 9) Privacy And Git Hygiene

This project handles sensitive financial data.

If/when you initialize git, avoid committing raw documents, extracted text, or ledger outputs. At minimum, keep these private:

- `data/inbox/`
- `data/sources/`
- `data/ledger/`
- `data/reports/`
- `data/charts/`
- `data/alerts/state.json`
- `data/alerts/events.jsonl`

## 10) Next Steps (Implementation Order)

If you are starting implementation, the spec lays out MVP milestones:

1. MVP-0: doc registry + hashing, `manual.add`, `transactions.jsonl` writer
2. MVP-1: one bank CSV adapter end-to-end + dedup + export
3. MVP-2: daily report + rolling aggregates + chart series
4. MVP-3: alerts engine + events/state
5. MVP-4: PDF extraction + OCR + receipt linking
6. MVP-5: monthly report + recurring/anomaly detection + datasets

See `SKILL.md` for details.

## 11) Running Tests

```bash
python3 -m unittest discover -s tests
```

## 12) Run The Webapp + API

The server exposes the same core operations as the CLI over HTTP (plus a minimal web UI).

```bash
python3 -m ledgerflow init
python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```

Useful URLs:

- Web UI: http://127.0.0.1:8787/
- OpenAPI docs: http://127.0.0.1:8787/docs
- Health: http://127.0.0.1:8787/api/health
