# API

LedgerFlow ships a local FastAPI server (same operations as the CLI, exposed over HTTP).

Run:

```bash
python3 -m ledgerflow init
python3 -m ledgerflow serve --host 127.0.0.1 --port 8787
```

OpenAPI:

- http://127.0.0.1:8787/docs

## Health

`GET /api/health`

Response:

```json
{ "status": "ok", "version": "0.1.0", "dataDir": "data" }
```

## OCR

Capabilities:

- `GET /api/ocr/capabilities`

Extract text from uploaded file:

- `POST /api/ocr/extract-upload` (multipart/form-data, field `file`)

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

## Import Receipt / Bill Upload

`POST /api/import/receipt-upload` (multipart/form-data)

Fields:

- `file` (required)
- `currency` (default `USD`)
- `copy_into_sources` (`true|false`, default `false`)

`POST /api/import/bill-upload` (multipart/form-data)

Fields:

- `file` (required)
- `currency` (default `USD`)
- `copy_into_sources` (`true|false`, default `false`)

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

## Alerts

- `POST /api/alerts/run` body: `{ "at": "2026-02-10", "commit": true }`
- `GET /api/alerts/events?limit=50`

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
