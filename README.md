# LedgerFlow

![LedgerFlow Logo](assets/logo.svg)

LedgerFlow is a local-first bills and receipts money tracker with:

- append-only ledger storage
- deterministic rebuild via correction events
- CLI + FastAPI + web UI
- OCR/PDF ingestion for receipts and bills
- reports, alerts, and chart datasets
- AI spending analysis (local-first + optional LLM narratives)
- review queue and reconciliation workflows

## Highlights

- Inputs:
  - bank CSV exports
  - bank/integration JSON exports
  - connector JSON payloads (`plaid`, `wise`)
  - receipt/bill files (`txt`, `pdf`, image formats)
  - manual entries
- Outputs:
  - `data/ledger/transactions.jsonl` and `data/ledger/corrections.jsonl`
  - daily/monthly reports
  - chart-ready JSON datasets
  - alert events + persistent alert/delivery state + outbox log
- Operations:
  - idempotent source registration and bank import (CSV/JSON)
  - receipt/bill parsing + source artifacts
  - transaction linking (`receipt`/`bill` to `bank_csv`)
  - manual-vs-bank duplicate marking
  - automation queue + scheduler jobs
  - review queue + resolution
- Runtime surfaces:
  - CLI: `python3 -m ledgerflow ...`
  - API: `/api/*` (FastAPI)
  - Web UI: `/`

## Quick Start

```bash
cd /Users/srinivaspendela/Sriinnu/Personal/Ledgerflow
python3 -m pip install -r requirements.txt

# Initialize local data layout
python3 -m ledgerflow init

# Import a bank CSV (dry-run, then commit)
python3 -m ledgerflow import csv data/inbox/bank/statement.csv --sample 5
python3 -m ledgerflow import csv data/inbox/bank/statement.csv --commit

# Import bank/integration JSON (dry-run, then commit)
python3 -m ledgerflow import bank-json data/inbox/bank/export.json --sample 5
python3 -m ledgerflow import bank-json data/inbox/bank/export.json --commit

# Import connector payload (plaid/wise adapters)
python3 -m ledgerflow connectors list
python3 -m ledgerflow import connector --connector plaid data/inbox/bank/plaid.json --commit

# Add a manual transaction
python3 -m ledgerflow manual add \
  --occurred-at 2026-02-10 \
  --amount -12.30 \
  --currency USD \
  --merchant "Farmers Market" \
  --category-hint groceries \
  --tags cash

# Build caches + reports/charts/alerts
python3 -m ledgerflow build
python3 -m ledgerflow report daily --date 2026-02-10
python3 -m ledgerflow report monthly --month 2026-02
python3 -m ledgerflow charts series --from-date 2026-02-01 --to-date 2026-02-29
python3 -m ledgerflow alerts run --at 2026-02-10
python3 -m ledgerflow alerts deliver
python3 -m ledgerflow alerts outbox --limit 20
python3 -m ledgerflow ai analyze --month 2026-02 --provider heuristic

# Automation queue examples
python3 -m ledgerflow automation enqueue --task-type build
python3 -m ledgerflow automation run-next --worker-id cli-worker
```

## AI Analysis (Local Models + LLMs)

```bash
# local heuristic only
python3 -m ledgerflow ai analyze --month 2026-02 --provider heuristic --json

# local model via Ollama
python3 -m ledgerflow ai analyze --month 2026-02 --provider ollama --model llama3.1:8b --json

# auto (ollama -> openai -> heuristic fallback)
python3 -m ledgerflow ai analyze --month 2026-02 --provider auto --json
```

Notes:

- `--provider auto` tries `ollama` first, then `openai`, then falls back to local `heuristic`.
- `--lookback-months` defaults to `6` months (including the target month).
- `--json` prints the full analysis payload for automation/API-style consumption.
- `--model` overrides provider defaults. Without an override, OpenAI uses `gpt-4.1-mini`; Ollama uses `OLLAMA_MODEL` or `llama3.1:8b`.
- Provider environment variables:
  - OpenAI: `OPENAI_API_KEY`
  - Ollama: `OLLAMA_URL` (default `http://127.0.0.1:11434/api/generate`) and optional `OLLAMA_MODEL`
- Response now includes:
  - `recommendations` (actionable next steps)
  - `savingsOpportunities` (category-level 10% reduction targets)
  - `confidence` (`level`, `score`, `reasons`)
  - `explainability.evidence` (why each risk/recommendation was produced)

## Automation (Queue + Scheduler)

```bash
# List queue tasks
python3 -m ledgerflow automation tasks --limit 25

# Enqueue due scheduler jobs, then run one task
python3 -m ledgerflow automation run-due
python3 -m ledgerflow automation run-next --worker-id cli-worker

# Enqueue alert delivery as a queue task
python3 -m ledgerflow automation enqueue --task-type alerts.deliver --payload-json '{"limit":100}'

# Run worker loop
python3 -m ledgerflow automation worker --worker-id cli-worker --max-tasks 20

# Scheduler + worker dispatch in one step
python3 -m ledgerflow automation dispatch --worker-id cli-dispatcher --max-tasks 20

# Queue health and failures
python3 -m ledgerflow automation stats
python3 -m ledgerflow automation dead-letters --limit 20
```

Job schedule validation is enforced (`daily|weekly|hourly` only, with strict `HH:MM` for timed schedules).

## Alert Delivery Channels

Alert rule evaluation writes events to `data/alerts/events.jsonl`. Delivery routes those events to channels defined in `data/alerts/delivery_rules.json`.

Default config writes to a local outbox:

```json
{
  "version": 1,
  "channels": [
    { "id": "local_outbox", "type": "outbox", "enabled": true }
  ]
}
```

Supported channel types:

- `outbox`: append payloads to `data/alerts/outbox.jsonl`
- `stdout`: print payload JSON to stdout
- `webhook`: POST JSON to configured URL

## Bank JSON Mapping

For nested integration payloads, provide a mapping file:

```bash
python3 -m ledgerflow import bank-json data/inbox/bank/nested.json \
  --mapping-file data/inbox/bank/mapping.json \
  --commit
```

Example `mapping.json`:

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

## Backup / Restore + Ops

```bash
# Create backup archive from --data-dir
python3 -m ledgerflow backup create
python3 -m ledgerflow backup create --out /tmp/ledgerflow.tar.gz --no-inbox

# Restore into a target directory
python3 -m ledgerflow backup restore --archive /tmp/ledgerflow.tar.gz --target-dir /tmp/ledgerflow-restored
python3 -m ledgerflow backup restore --archive /tmp/ledgerflow.tar.gz --target-dir /tmp/ledgerflow-restored --force

# Ops metrics snapshot
python3 -m ledgerflow ops metrics
```

## OCR Through CLI

```bash
# Capability checks
python3 -m ledgerflow ocr doctor

# Extract text with explicit OCR backend control
python3 -m ledgerflow ocr extract /path/to/receipt.jpg --image-provider auto --json
python3 -m ledgerflow ocr extract /path/to/receipt.jpg --image-provider tesseract --no-preprocess

# Receipt/Bill ingestion (uses extraction internally)
python3 -m ledgerflow import receipt data/inbox/receipts/receipt.jpg --image-provider openai
python3 -m ledgerflow import bill data/inbox/bills/invoice.pdf
```

## Run API + Web

```bash
python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```

- Web UI: http://127.0.0.1:8787/
- API docs: http://127.0.0.1:8787/docs

Optional API protection:

```bash
LEDGERFLOW_API_KEY=change-me python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```

Scoped keys (preferred):

```bash
LEDGERFLOW_API_KEYS='[
  {"id":"reader","key":"reader-token","scopes":["read"],"enabled":true},
  {"id":"writer","key":"writer-token","scopes":["write"],"enabled":true},
  {"id":"ops","key":"ops-token","scopes":["admin"],"expiresAt":"2099-01-01T00:00:00Z"}
]' python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```

Auth default is already tightened:

- without key env vars, API is local-only
- non-local API calls are denied

Key behavior:

- `/api/health` remains unauthenticated
- `read` scope permits `GET`/`HEAD`
- `write` scope permits mutating calls and also satisfies read access
- `admin` scope includes `read` + `write`
- keys with `"enabled": false` are rejected
- keys with past `"expiresAt"` are rejected
- route-level scopes are supported:
  - `/api/automation/*` requires `automation`
  - `/api/alerts/deliver` requires `automation`
  - `/api/ops/metrics` requires `ops`
  - `/api/backup/*` and `/api/auth/keys` require `admin`
- optional key workspaces:
  - add `"workspaces": ["team-a","team-b"]` in key config
  - send `X-Workspace-Id: team-a` on API requests

Auth headers:

- `X-API-Key: <token>`
- `Authorization: Bearer <token>`

Mutating API requests are logged to `data/meta/audit.jsonl`.

## Docker

```bash
docker build -t ledgerflow .
docker run --rm -p 8787:8787 -v "$PWD/data:/data" ledgerflow
```

## Demo Dataset + Script

Sample onboarding assets are included:

- `/Users/srinivaspendela/Sriinnu/Personal/Ledgerflow/samples/inbox/bank/statement.csv`
- `/Users/srinivaspendela/Sriinnu/Personal/Ledgerflow/samples/inbox/receipts/receipt_farmers_market.txt`
- `/Users/srinivaspendela/Sriinnu/Personal/Ledgerflow/samples/inbox/bills/invoice_city_power.txt`
- `/Users/srinivaspendela/Sriinnu/Personal/Ledgerflow/samples/manual_entries.json`

Run the full end-to-end demo:

```bash
./scripts/demo_onboarding.sh
```

Optional custom demo data directory:

```bash
./scripts/demo_onboarding.sh /absolute/path/to/demo-data
```

## Testing

```bash
python3 -m unittest discover -s tests
```

## CI

GitHub Actions workflow: `.github/workflows/ci.yml`

Runs:

- Ruff lint
- Mypy type check
- Unit tests
- CLI smoke commands

## Project Docs

- Getting started: `GETTING_STARTED.md`
- CLI: `docs/CLI.md`
- API: `docs/API.md`
- Schemas: `docs/SCHEMAS.md`
- Data layout: `docs/DATA_LAYOUT.md`
- Development: `docs/DEVELOPMENT.md`
- Roadmap status: `docs/ROADMAP.md`
- Changelog: `CHANGELOG.md`
- Product spec source: `SKILL.md`
