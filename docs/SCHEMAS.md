# Schemas (MVP)

These are the shapes LedgerFlow currently writes.

## Transaction (`data/ledger/transactions.jsonl`)

Notes:

- `amount.value` is a decimal string (to avoid float rounding issues).
- `source.sourceHash` is used for idempotency/dedup.

Example:

```json
{
  "txId": "tx_...",
  "source": {
    "docId": "doc_...",
    "sourceType": "manual",
    "sourceHash": "sha256:...",
    "lineRef": "manual:entry:1"
  },
  "postedAt": "2026-02-10",
  "occurredAt": "2026-02-10",
  "amount": { "value": "-12.30", "currency": "USD" },
  "direction": "debit",
  "merchant": "Farmers Market",
  "description": "cash vegetables",
  "category": { "id": "groceries", "confidence": 1.0, "reason": "category_hint" },
  "tags": ["cash"],
  "confidence": { "extraction": 1.0, "normalization": 1.0, "categorization": 1.0 },
  "links": { "receiptDocId": null, "billDocId": null },
  "createdAt": "2026-02-10T21:09:34Z"
}
```

## CorrectionEvent (`data/ledger/corrections.jsonl`)

Example:

```json
{
  "eventId": "evt_...",
  "txId": "tx_...",
  "type": "patch",
  "patch": { "category": { "id": "restaurants" } },
  "reason": "user_override",
  "at": "2026-02-10T21:11:00Z"
}
```

## Sources Index (`data/sources/index.json`)

Example:

```json
{
  "version": 1,
  "docs": [
    {
      "docId": "doc_...",
      "originalPath": "data/inbox/bank/statement.csv",
      "storedPath": "data/sources/doc_.../original.csv",
      "sourceType": "receipt|bill|...",
      "sha256": "...",
      "size": 12345,
      "addedAt": "2026-02-10T21:09:34Z"
    }
  ]
}
```

## Receipt/Bill Parse (`data/sources/<docId>/parse.json`)

Receipt example:

```json
{
  "type": "receipt",
  "docId": "doc_...",
  "merchant": "FARMERS MARKET",
  "date": "2026-02-10",
  "total": { "value": "12.30", "currency": "USD" },
  "vat": [],
  "parser": { "name": "receipt_parser", "version": "2.0", "template": "simple_total_line" },
  "confidenceBreakdown": { "merchant": 0.3, "date": 0.25, "total": 0.35, "vat": 0.1 },
  "missingFields": [],
  "needsReview": false,
  "confidence": 1.0,
  "extraction": { "method": "text|pdfplumber|pypdf|pytesseract" },
  "parsedAt": "2026-02-10T21:20:00Z"
}
```

Bill example:

```json
{
  "type": "bill",
  "docId": "doc_...",
  "vendor": "ACME UTILITIES",
  "date": "2026-02-01",
  "dueDate": "2026-02-15",
  "amount": { "value": "89.99", "currency": "USD" },
  "references": { "invoiceNumber": "INV-123" },
  "parser": { "name": "bill_parser", "version": "2.0", "template": "standard_invoice" },
  "confidenceBreakdown": { "vendor": 0.25, "amount": 0.4, "dates": 0.2, "invoiceNumber": 0.15 },
  "missingFields": [],
  "needsReview": false,
  "confidence": 0.8,
  "extraction": { "method": "text|pdfplumber|pypdf" },
  "parsedAt": "2026-02-10T21:20:00Z"
}
```

## Alerts

Events (`data/alerts/events.jsonl`):

```json
{
  "eventId": "alrt_...",
  "ruleId": "groceries_monthly",
  "type": "category_budget",
  "period": "month",
  "periodKey": "2026-02",
  "scopeDate": "2026-02-10",
  "at": "2026-02-10T21:21:00Z",
  "data": { "categoryId": "groceries", "limit": "600", "value": "650.12", "txIds": ["tx_..."] },
  "message": "..."
}
```

State (`data/alerts/state.json`):

```json
{
  "version": 1,
  "lastRun": "2026-02-10T21:21:10Z",
  "rules": {
    "groceries_monthly": { "lastTriggeredPeriodKey": "2026-02", "lastValue": "650.12" }
  }
}
```

Delivery rules (`data/alerts/delivery_rules.json`):

```json
{
  "version": 1,
  "channels": [
    { "id": "local_outbox", "type": "outbox", "enabled": true },
    { "id": "ops_webhook", "type": "webhook", "enabled": false, "url": "https://example.com/hooks/ledgerflow", "headers": { "Authorization": "Bearer ..." } }
  ]
}
```

Delivery state (`data/alerts/delivery_state.json`):

```json
{
  "version": 1,
  "lastRun": "2026-02-10T21:25:00Z",
  "channels": {
    "local_outbox": { "cursor": 42, "lastDeliveredEventId": "alrt_...", "lastDeliveredAt": "2026-02-10T21:25:00Z", "lastError": null }
  }
}
```

Outbox (`data/alerts/outbox.jsonl`):

```json
{
  "deliveryId": "adel_...",
  "channelId": "local_outbox",
  "channelType": "outbox",
  "eventId": "alrt_...",
  "deliveredAt": "2026-02-10T21:25:01Z",
  "event": { "eventId": "alrt_...", "ruleId": "groceries_monthly" }
}
```

## Charts

Series (`data/charts/series.<from>_<to>.json`):

```json
{
  "granularity": "day",
  "from": "2026-02-01",
  "to": "2026-02-29",
  "generatedAt": "2026-02-10T21:22:00Z",
  "points": [
    { "t": "2026-02-01", "spend": "34.20", "income": "0", "net": "-34.20", "currency": "USD" }
  ]
}
```

Category breakdown (`data/charts/category_breakdown.<YYYY-MM>.json`) and merchant top (`data/charts/merchant_top.<YYYY-MM>.json`) follow the same pattern (see `/ledgerflow/charts.py`).

## Derived Ledger Caches

Build summary (`data/ledger/summary.json`):

```json
{
  "generatedAt": "2026-02-10T21:23:00Z",
  "fromDate": null,
  "toDate": null,
  "days": ["2026-02-10"],
  "months": ["2026-02"],
  "appliedCorrections": 0,
  "deletedTxCount": 0
}
```
