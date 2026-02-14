# API

LedgerFlow ships a local FastAPI server (same operations as the CLI, exposed over HTTP).

Run:

```bash
python3 -m ledgerflow init
python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```

OpenAPI:

- http://127.0.0.1:8787/docs

Auth behavior:

- Without key env vars, API allows local clients only (`127.0.0.1`, `::1`).
- Non-local API access is denied unless keys are configured.
- Auth headers are accepted as:
  - `X-API-Key: <token>`
  - `Authorization: Bearer <token>`
- Env vars:
  - `LEDGERFLOW_API_KEY=<token>`: legacy single full-access key.
  - `LEDGERFLOW_API_KEYS=<json>`: scoped keys (preferred).

`LEDGERFLOW_API_KEYS` JSON formats:

```json
[
  { "id": "reader", "key": "reader-token", "scopes": ["read"], "enabled": true },
  { "id": "writer", "key": "writer-token", "scopes": ["write"], "enabled": true },
  { "id": "ops", "key": "ops-token", "scopes": ["admin"], "expiresAt": "2099-01-01T00:00:00Z" }
]
```

or:

```json
{
  "reader": { "key": "reader-token", "scopes": ["read"] },
  "writer": { "key": "writer-token", "scopes": ["write"] }
}
```

Scope rules:

- `/api/health` is always unauthenticated.
- `GET`/`HEAD` require `read`.
- mutating methods (`POST`, etc.) require `write`.
- `write` implicitly satisfies `read`.
- `admin` satisfies both `read` and `write`.
- keys with `"enabled": false` are rejected.
- keys with past `"expiresAt"` are rejected.

Feature-level scopes:

- `/api/automation/*` additionally requires `automation`.
- `/api/alerts/deliver` additionally requires `automation`.
- `/api/ops/metrics` additionally requires `ops`.
- `/api/backup/*` and `/api/auth/keys` additionally require `admin`.

Workspace restrictions:

- Keys may include `"workspaces": ["team-a", "team-b"]`.
- Requests should send `X-Workspace-Id: <workspace>`.
- If key workspaces are configured, requests outside allowed workspaces are denied.

## Health

`GET /api/health`

Response:

```json
{ "status": "ok", "version": "0.2.1", "dataDir": "data", "authEnabled": false, "authMode": "local_only_no_key" }
```

`authMode` values:

- `local_only_no_key`
- `api_key` (legacy key)
- `api_key_scoped` (any scoped key configured)

`GET /api/auth/context` returns current key auth context for the presented key.

`GET /api/auth/keys` lists configured key metadata (ids/scopes/status, no raw tokens).

Connectors catalog:

- `GET /api/connectors`

## OCR

Capabilities:

- `GET /api/ocr/capabilities`

Extract text from uploaded file:

- `POST /api/ocr/extract-upload` (multipart/form-data)
- fields: `file`, `image_provider` (`auto|pytesseract|tesseract|openai`), `preprocess` (`true|false`)

Extract text from a file path:

- `POST /api/ocr/extract-path`
- body: `{ "path": "...", "imageProvider": "auto", "preprocess": true }`

## Index / Migrations

- `GET /api/index/stats`
- `POST /api/index/rebuild`
- `GET /api/migrate/status`
- `POST /api/migrate/up` body: `{ "to": 2 }` (optional target)

## Initialize Data Layout

`POST /api/init`

Body:

```json
true
```

Meaning: `write_defaults` (boolean). If `true`, writes starter config files when missing.

## Transactions / Corrections

`GET /api/transactions?limit=50`

`GET /api/corrections?limit=50`

## Build Derived Caches

`POST /api/build`

Body (all optional):

```json
{ "fromDate": "2026-02-01", "toDate": "2026-02-29", "includeDeleted": false }
```

## Sources Index

`GET /api/sources?limit=200`

## Review Queue

- `GET /api/review/queue?date=YYYY-MM-DD&limit=200`
- `POST /api/review/resolve`

Example resolve payload:

```json
{
  "txId": "tx_...",
  "patch": { "category": { "id": "groceries", "confidence": 1.0, "reason": "review_resolve" } },
  "reason": "review_resolve"
}
```

## Manual Add

`POST /api/manual/add`

Body:

```json
{
  "occurredAt": "2026-02-10",
  "amount": { "value": "-12.30", "currency": "USD" },
  "merchant": "Farmers Market",
  "description": "cash vegetables",
  "categoryHint": "groceries",
  "tags": ["cash"],
  "links": { "receiptDocId": null, "billDocId": null }
}
```

## Manual Edit (CorrectionEvent)

`POST /api/manual/edit`

Body:

```json
{
  "txId": "tx_...",
  "patch": { "category": { "id": "restaurants" } },
  "reason": "user_override"
}
```

## Manual Delete (Tombstone)

`POST /api/manual/delete`

Body:

```json
{ "txId": "tx_...", "reason": "user_delete" }
```

## Manual Bulk Add

`POST /api/manual/bulk-add`

Body: JSON array of manual-entry objects (same shape as `/api/manual/add` but without wrapping):

```json
[
  {
    "occurredAt": "2026-02-10",
    "amount": { "value": "-12.30", "currency": "USD" },
    "merchant": "Farmers Market",
    "categoryHint": "groceries",
    "tags": ["cash"]
  }
]
```

## Register Upload As Source

`POST /api/sources/register-upload` (multipart/form-data)

Fields:

- `file` (required)
- `copy_into_sources` (optional boolean, default `false`)
- `source_type` (optional string, example: `receipt`, `bill`, `bank_csv`)

## Import CSV Upload

`POST /api/import/csv-upload` (multipart/form-data)

Fields (most are optional):

- `file` (required)
- `commit` (`true|false`, default `false`)
- `copy_into_sources` (`true|false`, default `false`)
- `encoding` (default `utf-8-sig`)
- `currency` (default `USD`)
- `date_format` (optional)
- `day_first` (`true|false`, default `false`)
- `sample` (default `5`)
- `max_rows` (optional)
- `mapping_json` (optional JSON object string for nested field mapping)

Optional explicit mapping:

- `date_col`, `description_col`, `amount_col`, `debit_col`, `credit_col`, `currency_col`

## Import CSV From Path

`POST /api/import/csv-path`

Body:

```json
{
  "path": "/absolute/or/relative/path/to/file.csv",
  "commit": false,
  "copyIntoSources": false,
  "encoding": "utf-8-sig",
  "currency": "USD",
  "dateFormat": "%Y-%m-%d",
  "dayFirst": false,
  "sample": 5,
  "maxRows": 200
}
```

## Import Bank JSON Upload

`POST /api/import/bank-json-upload` (multipart/form-data)

Fields:

- `file` (required)
- `commit` (`true|false`, default `false`)
- `copy_into_sources` (`true|false`, default `false`)
- `currency` (default `USD`)
- `sample` (default `5`)
- `max_rows` (optional)

Input JSON file may be either:

- a list of transaction objects, or
- an object with `transactions: [...]`.

## Import Bank JSON From Path

`POST /api/import/bank-json-path`

Body:

```json
{
  "path": "/absolute/or/relative/path/to/file.json",
  "commit": false,
  "copyIntoSources": false,
  "currency": "USD",
  "sample": 5,
  "maxRows": 200,
  "mapping": {
    "date": "meta.date",
    "amount": "money.value",
    "currency": "money.currency",
    "merchant": "meta.merchant.name",
    "description": "notes.text",
    "category": "labels.category"
  }
}
```

## Import Connector Payload From Path

`POST /api/import/connector-path`

Body:

```json
{
  "connector": "plaid",
  "path": "/absolute/or/relative/path/to/payload.json",
  "commit": false,
  "copyIntoSources": false,
  "currency": "USD",
  "sample": 5,
  "maxRows": 200
}
```

## Import Receipt / Bill Upload

`POST /api/import/receipt-upload` (multipart/form-data)

Fields:

- `file` (required)
- `currency` (default `USD`)
- `copy_into_sources` (`true|false`, default `false`)
- `image_provider` (`auto|pytesseract|tesseract|openai`, default `auto`)
- `preprocess` (`true|false`, default `true`)

`POST /api/import/bill-upload` (multipart/form-data)

Fields:

- `file` (required)
- `currency` (default `USD`)
- `copy_into_sources` (`true|false`, default `false`)
- `image_provider` (`auto|pytesseract|tesseract|openai`, default `auto`)
- `preprocess` (`true|false`, default `true`)

## Link Receipts

`POST /api/link/receipts`

Body (all optional):

```json
{ "maxDaysDiff": 3, "amountTolerance": "0.01", "commit": true }
```

Link bills:

`POST /api/link/bills`

Body (all optional):

```json
{ "maxDaysDiff": 7, "amountTolerance": "0.01", "commit": true }
```

## Reports

Generate:

- `POST /api/report/daily` body: `{ "date": "2026-02-10" }`
- `POST /api/report/monthly` body: `{ "month": "2026-02" }`

Fetch markdown:

- `GET /api/report/daily/{YYYY-MM-DD}`
- `GET /api/report/monthly/{YYYY-MM}`

## Charts

- `POST /api/charts/series` body: `{ "fromDate": "2026-02-01", "toDate": "2026-02-29" }`
- `POST /api/charts/month` body: `{ "month": "2026-02", "limit": 25 }`

## AI Analysis

- `POST /api/ai/analyze`

Request body:

```json
{
  "month": "2026-02",
  "provider": "auto",
  "model": null,
  "lookbackMonths": 6
}
```

Request defaults:

- `month` defaults to the current month (`YYYY-MM`)
- `provider` defaults to `auto`
- `lookbackMonths` defaults to `6`
- `model` is optional and provider-specific

Provider behavior:

- `auto`: tries `ollama`, then `openai`, then falls back to local heuristic output.
- `heuristic`: local analysis only, no model API calls.
- `ollama`: local model call via `OLLAMA_URL`; falls back to heuristic narrative on failure.
- `openai`: OpenAI Responses API call; falls back to heuristic narrative on failure.

Provider environment variables:

- OpenAI: `OPENAI_API_KEY`
- Ollama: `OLLAMA_URL` (default `http://127.0.0.1:11434/api/generate`) and optional `OLLAMA_MODEL`

Response shape (`200`):

- `month`, `generatedAt`
- `providerRequested`, `providerUsed`, `model`
- `currency`
- `summary` (target-month `spend`, `income`, `net`)
- `quality` (`totalSpend`, `unclassifiedSpend`, `unclassifiedPct`, `manualSpend`, `manualPct`)
- `topCategories`, `topMerchants`
- `riskFlags`, `insights`, `recommendations`, `narrative`
- `savingsOpportunities` (category-level reduction scenarios)
- `confidence` (`level`, `score`, `reasons`)
- `explainability.evidence` (rule-level evidence summary)
- `datasets.monthlySpendTrend`, `datasets.categoryTrend`, `datasets.spendForecast`
- `llmError` (set when a model provider fails and heuristic fallback is used)

## Automation

Queue listing:

- `GET /api/automation/tasks?limit=100&status=queued,running`
- `GET /api/automation/stats`
- `GET /api/automation/dead-letters?limit=50`

Enqueue task:

- `POST /api/automation/tasks`
- body:

```json
{
  "taskType": "build",
  "payload": {},
  "runAt": "2026-02-13T09:00:00Z",
  "maxRetries": 2
}
```

Run one worker step:

- `POST /api/automation/run-next`
- body (optional): `{ "workerId": "api-worker" }`

Enqueue scheduled jobs due now:

- `POST /api/automation/run-due`
- body (optional): `{ "at": "2026-02-13T09:00:00Z" }`

Dispatch scheduler + worker in one call:

- `POST /api/automation/dispatch`
- body (all optional):

```json
{
  "runDue": true,
  "at": "2026-02-13T09:00:00Z",
  "workerId": "api-dispatcher",
  "maxTasks": 10,
  "pollSeconds": 0.0
}
```

Jobs config:

- `GET /api/automation/jobs`
- `POST /api/automation/jobs` (replace jobs document)

## Backup / Restore

Create a backup archive from current server data dir:

- `POST /api/backup/create`
- body (all optional):

```json
{
  "outPath": "/tmp/ledgerflow-backup.tar.gz",
  "includeInbox": true
}
```

Restore a backup archive into target directory:

- `POST /api/backup/restore`
- body:

```json
{
  "archivePath": "/tmp/ledgerflow-backup.tar.gz",
  "targetDir": "/tmp/ledgerflow-restored",
  "force": false
}
```

## Ops Metrics

- `GET /api/ops/metrics`
- response includes:
  - `index` (sqlite index stats)
  - `queue` (automation queue stats)
  - `counts` (`sources`, `alertsEvents`, `alertsOutbox`, `auditEvents`, `transactionsJsonl`, `correctionsJsonl`)

## Alerts

- `POST /api/alerts/run` body: `{ "at": "2026-02-10", "commit": true }`
- `GET /api/alerts/events?limit=50`
- `POST /api/alerts/deliver` body:

```json
{ "limit": 100, "channels": ["local_outbox"], "dryRun": false }
```

- `GET /api/alerts/outbox?limit=50`

## Audit

- `GET /api/audit/events?limit=100`

## Export

`POST /api/export/csv` returns a `text/csv` file response.

Body (all optional):

```json
{ "fromDate": "2026-02-01", "toDate": "2026-02-29", "includeDeleted": false }
```

## Dedup / Reconciliation

`POST /api/dedup/manual-vs-bank`

Body (all optional):

```json
{ "fromDate": "2026-02-01", "toDate": "2026-02-29", "maxDaysDiff": 1, "amountTolerance": "0.01", "commit": true }
```
