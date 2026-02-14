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

## Import Bank JSON

Dry-run (prints normalized transaction samples):

```bash
python3 -m ledgerflow import bank-json data/inbox/bank/export.json --sample 5
```

Commit import:

```bash
python3 -m ledgerflow import bank-json data/inbox/bank/export.json --commit
```

Useful flags:

- `--currency USD` (default currency if rows omit it)
- `--copy-into-sources` (store original file under `data/sources/<docId>/`)
- `--max-rows <n>` (limit processed rows)
- `--mapping-file <path>` (optional JSON field map for nested integration exports)

Input shape:

- JSON list of transaction objects, or
- object containing `transactions: [...]`

When the payload uses nested fields, pass `--mapping-file` with dot-paths (for example `meta.date`, `money.value`).

Example mapping file (`mapping.json`):

```json
{
  "date": "meta.date",
  "amount": "money.value",
  "currency": "money.currency",
  "merchant": "meta.merchant.name",
  "description": "notes.text",
  "category": "labels.category"
}
```

## Connectors

List available connector adapters:

```bash
python3 -m ledgerflow connectors list
```

Import connector payload:

```bash
python3 -m ledgerflow import connector --connector plaid data/inbox/bank/plaid.json --sample 5
python3 -m ledgerflow import connector --connector plaid data/inbox/bank/plaid.json --commit
python3 -m ledgerflow import connector --connector wise data/inbox/bank/wise.json --commit
```

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

## AI Spending Analysis

Run AI/local-model assisted spending analysis:

```bash
python3 -m ledgerflow ai analyze --month 2026-02 --provider auto --json
```

Local-only heuristic analysis:

```bash
python3 -m ledgerflow ai analyze --month 2026-02 --provider heuristic
```

Local model via Ollama:

```bash
python3 -m ledgerflow ai analyze --month 2026-02 --provider ollama --model llama3.1:8b --json
```

Flags:

- `--provider auto|heuristic|ollama|openai`
- `--model <name>` (optional override; OpenAI default: `gpt-4.1-mini`, Ollama default: `OLLAMA_MODEL` or `llama3.1:8b`)
- `--lookback-months <n>` (default: `6`, including the target month)
- `--json` (emit the full JSON payload instead of narrative + bullet formatting)

Provider behavior:

- `auto` tries `ollama`, then `openai`, then local `heuristic` fallback.
- `heuristic` stays local and does not call external model APIs.
- `ollama` and `openai` try only the selected provider, with heuristic fallback output if that provider fails.

Provider environment variables:

- OpenAI: `OPENAI_API_KEY`
- Ollama: `OLLAMA_URL` (default `http://127.0.0.1:11434/api/generate`) and optional `OLLAMA_MODEL`

Output highlights:

- `recommendations` and `savingsOpportunities`
- `confidence` with score/level/reasons
- `explainability.evidence` for traceability

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

Supported rule types now include:

- `category_budget`
- `recurring_new`
- `merchant_spike`
- `recurring_changed`
- `cash_heavy_day`
- `unclassified_spend`

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

## Review Queue

List review items (low-confidence transaction categorization and low-confidence source parses):

```bash
python3 -m ledgerflow review queue --date 2026-02-10 --limit 100
```

Resolve a transaction review item via CorrectionEvent patch:

```bash
python3 -m ledgerflow review resolve --tx-id tx_... --set-category groceries
```

## Automation Queue + Scheduler

List queue tasks:

```bash
python3 -m ledgerflow automation tasks --limit 25
python3 -m ledgerflow automation tasks --status queued,running
```

Enqueue a task:

```bash
python3 -m ledgerflow automation enqueue --task-type build
python3 -m ledgerflow automation enqueue \
  --task-type alerts.run \
  --payload-json '{"at":"2026-02-10","commit":true}'
```

Run scheduler and worker steps:

```bash
python3 -m ledgerflow automation run-due
python3 -m ledgerflow automation run-next --worker-id cli-worker
python3 -m ledgerflow automation worker --worker-id cli-worker --max-tasks 20
```

Dispatch scheduler + worker in one command:

```bash
python3 -m ledgerflow automation dispatch --worker-id cli-dispatcher --max-tasks 20
```

Queue health and failure inspection:

```bash
python3 -m ledgerflow automation stats
python3 -m ledgerflow automation dead-letters --limit 20
```

## Backup / Restore

Create backup archive from current `--data-dir`:

```bash
python3 -m ledgerflow backup create
python3 -m ledgerflow backup create --out /tmp/ledgerflow.tar.gz --no-inbox
```

Restore backup archive into a target directory:

```bash
python3 -m ledgerflow backup restore --archive /tmp/ledgerflow.tar.gz --target-dir /tmp/ledgerflow-restore
python3 -m ledgerflow backup restore --archive /tmp/ledgerflow.tar.gz --target-dir /tmp/ledgerflow-restore --force
```

## Ops Metrics

```bash
python3 -m ledgerflow ops metrics
```

Manage job definitions:

```bash
python3 -m ledgerflow automation jobs-list
python3 -m ledgerflow automation jobs-set --file data/automation/jobs.json
```

## Run Webapp + API Server

```bash
python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```

Dev-only:

- `--reload` enables auto-reload

Auth environment variables:

- `LEDGERFLOW_API_KEY=<token>`: legacy full-access key
- `LEDGERFLOW_API_KEYS=<json>`: scoped key store (preferred)

`LEDGERFLOW_API_KEYS` accepted JSON shapes:

```bash
# list shape
LEDGERFLOW_API_KEYS='[
  {"id":"reader","key":"reader-token","scopes":["read"],"enabled":true},
  {"id":"writer","key":"writer-token","scopes":["write"],"enabled":true},
  {"id":"ops","key":"ops-token","scopes":["admin"],"expiresAt":"2099-01-01T00:00:00Z"}
]'
```

```bash
# object shape
LEDGERFLOW_API_KEYS='{
  "reader": {"key":"reader-token","scopes":["read"]},
  "writer": {"key":"writer-token","scopes":["write"]}
}'
```

Scope behavior:

- `read`: allows `GET`/`HEAD` `/api/*` routes
- `write`: allows mutating methods and implicitly covers `read`
- `admin`: includes both `read` and `write`
- `/api/health` is always unauthenticated
- `"enabled": false` disables a key
- past `"expiresAt"` timestamps invalidate a key

Feature scope behavior:

- `automation`: required for `/api/automation/*`
- `ops`: required for `/api/ops/metrics`
- `admin`: required for `/api/backup/*` and `/api/auth/keys`

Workspace-aware keys:

- Add `workspaces` list in `LEDGERFLOW_API_KEYS` entries.
- Pass `X-Workspace-Id` header when calling API.
