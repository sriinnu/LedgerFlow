Good. You just added the stuff that turns this from “parser demo” into a thing people actually use daily: manual entry, daily/monthly reports, alerts, and chart-ready aggregates.

Below is an updated SKILL.md you can paste over the existing one (or treat it as a patch). I kept it local-first, auditable, and buildable without boiling the ocean.

# SKILL: Bills + Receipts Money Tracker (Local-First)

> Working name: **LedgerFlow** (rename later)

## 0) Why this skill exists

People don’t need “budgeting”. They need **truth**:
- Ingest **bank CSVs**, **PDF bills**, and **daily receipts**
- Allow **manual daily entries** (cash, splits, edge cases)
- Normalize everything into a **single ledger**
- Produce **daily and monthly reports**
- Trigger **alerts** when spending goes off-script
- Provide **chart/graph datasets** for a UI

Local-first by default. No cloud required.

---

## 1) Goals

This skill must:
1) Import data from **bank CSVs** (multiple formats)
2) Import **PDF bills/invoices** (extract vendor, amount, due date, period, references)
3) Import **receipts** (PDF/image); extract merchant, date, total, currency, VAT lines (best-effort)
4) Support **manual entries** (quick daily spend, cash, corrections, splits)
5) Produce a normalized ledger + **reports** + **analytics datasets** for charts
6) Produce **alerts** based on category budgets, recurring charges, anomalies
7) Keep an auditable trail: every tx links back to its source + parse confidence

---

## 2) Non-goals (for v1)

- Perfect universal OCR/invoice parsing
- Tax/legal advice
- Auto-paying bills
- Cloud sharing by default

---

## 3) Inputs and Outputs

### Inputs
- `*.csv` bank exports (various schemas)
- `*.pdf` bills/invoices
- receipts: `*.pdf`, `*.jpg|*.png|*.webp`
- manual entries: JSON payloads / CLI prompts / UI form (via skill interface)

### Outputs
Ledger:
- `ledger/transactions.jsonl` (append-only)
- `ledger/monthly/<YYYY-MM>.json`
- `ledger/daily/<YYYY-MM-DD>.json` (optional cache)

Reports:
- `reports/daily/<YYYY-MM-DD>.md`
- `reports/monthly/<YYYY-MM>.md`

Chart datasets (UI-ready):
- `charts/series.<YYYY-MM>.json`
- `charts/category_breakdown.<YYYY-MM>.json`
- `charts/merchant_top.<YYYY-MM>.json`

Alerts:
- `alerts/events.jsonl` (what triggered)
- `alerts/state.json` (last-run markers, rolling sums)
- optional `alerts/outbox.jsonl` (if you route to channel/email later)

Parse artifacts:
- `sources/index.json`
- `sources/<docId>/parse.json`
- `sources/<docId>/raw.txt`
- `sources/<docId>/debug.*` (optional)

---

## 4) Dataflow

        +-------------------+
        | Sources           |
        | CSV / PDF / IMG   |
        | Manual Entry      |
        +---------+---------+
                  |
                  v
        +-------------------+
        | Extract / Parse   |
        | CSV / PDF / OCR   |
        | Manual validate   |
        +---------+---------+
                  |
                  v
        +-------------------+
        | Normalize + Merge |
        | dates/amounts     |
        | merchant/category |
        | dedup + linkages  |
        +---------+---------+
                  |
                  v
        +-------------------+
        | Ledger Store      |
        | append-only +     |
        | corrections log   |
        +---------+---------+
                  |
       +----------+----------+
       |                     |
       v                     v

+—————––+   +—————––+
| Reports           |   | Alerts Engine     |
| daily/monthly     |   | budgets/anomaly   |
+—————––+   +—————––+
|
v
+—————––+
| Chart Datasets    |
| series/buckets    |
+—————––+

---

## 5) Core entities (schemas)

### 5.1 Transaction (normalized)
```json
{
  "txId": "tx_01J....",
  "source": {
    "docId": "doc_01J....",
    "sourceType": "bank_csv|bill_pdf|receipt_pdf|receipt_img|manual",
    "sourceHash": "sha256:...",
    "lineRef": "csv:row:42|pdf:page:1:block:7|ocr:block:3|manual:entry:1"
  },
  "postedAt": "2026-02-10",
  "occurredAt": "2026-02-08",
  "amount": { "value": -24.90, "currency": "EUR" },
  "direction": "debit|credit",
  "merchant": "BILLA AG",
  "description": "CARD PAYMENT ...",
  "category": {
    "id": "groceries",
    "confidence": 0.92,
    "reason": "merchant_match:BILLA"
  },
  "tags": ["receipt-linked", "card"],
  "confidence": {
    "extraction": 0.88,
    "normalization": 0.97,
    "categorization": 0.92
  },
  "links": { "receiptDocId": "doc_...", "billDocId": null },
  "createdAt": "2026-02-10T08:01:22Z"
}

5.2 ManualEntry (input shape)

Manual entries are first-class; they produce Transactions with sourceType=manual.

{
  "occurredAt": "2026-02-10",
  "amount": { "value": -12.30, "currency": "EUR" },
  "merchant": "Farmers Market",
  "description": "cash vegetables",
  "categoryHint": "groceries",
  "tags": ["cash"],
  "attachments": ["optional: docId if user snapped receipt later"],
  "confidenceOverride": { "categorization": 1.0 }
}

5.3 CorrectionEvent (auditable edits, not silent mutation)

Instead of mutating history invisibly, store corrections as events.

{
  "eventId": "evt_01J...",
  "txId": "tx_01J...",
  "type": "set_category|set_merchant|set_occurredAt|link_receipt|split_tx|merge_tx",
  "patch": { "category": { "id": "restaurants" } },
  "reason": "user_override",
  "at": "2026-02-10T20:11:00Z"
}

Ledger build applies these events deterministically.

⸻

6) Interfaces (skill contract)

6.1 Core operations
	•	importDocuments(input)
	•	buildLedger(options)
	•	reportDaily(date)
	•	reportMonthly(month)
	•	export(format, range)
	•	charts(range, granularity)
	•	alerts.run(rangeOrNow)

6.2 Manual entry operations
	•	manual.add(entry) -> creates tx (sourceType=manual)
	•	manual.bulkAdd(entries[])
	•	manual.edit(txId, patch) -> writes CorrectionEvent
	•	manual.delete(txId) -> writes CorrectionEvent (tombstone), never hard-delete

6.3 Suggested command shapes (CLI/RPC)

{ "op": "manual.add", "entry": { "occurredAt": "2026-02-10", "amount": { "value": -12.30, "currency": "EUR" }, "merchant": "Farmers Market", "categoryHint": "groceries" } }
{ "op": "report.daily", "date": "2026-02-10" }
{ "op": "alerts.run", "scope": "now" }
{ "op": "charts", "range": { "from": "2026-02-01", "to": "2026-02-29" }, "granularity": "day" }


⸻

7) Reports

7.1 Daily report (what it should contain)
	•	total spend (debits) and net flow (credits - debits)
	•	top categories (today + rolling 7 days)
	•	top merchants (today)
	•	“review queue” items (low confidence parses)
	•	alerts triggered today

Output: reports/daily/YYYY-MM-DD.md and optional JSON for UI.

7.2 Monthly report
	•	totals + category breakdown
	•	recurring charges list (detected)
	•	anomalies/spikes (per category/merchant)
	•	“subscription drift” (recurring increased)
	•	manual vs imported ratio (helps spot missing receipts)

Output: reports/monthly/YYYY-MM.md

⸻

8) Alerts

Alerts are rules over rolling aggregates. They should be deterministic and stateful.

8.1 Alert rule types (v1)
	•	category budget exceeded (daily/weekly/monthly)
	•	merchant spend spike (relative to trailing window)
	•	recurring charge created (new subscription)
	•	recurring charge changed (amount changed > threshold)
	•	“cash-heavy day” (manual/cash entries exceed threshold)
	•	“unclassified spend” (category confidence low or missing)

8.2 Rule config (suggested)

data/alerts/alert_rules.json

{
  "currency": "EUR",
  "rules": [
    { "id": "groceries_monthly", "type": "category_budget", "categoryId": "groceries", "period": "month", "limit": 600 },
    { "id": "restaurants_weekly", "type": "category_budget", "categoryId": "restaurants", "period": "week", "limit": 120 },
    { "id": "new_recurring", "type": "recurring_new", "minOccurrences": 3, "spacingDays": [25, 35] }
  ]
}

8.3 Alert event output

Append-only events to alerts/events.jsonl, each includes ruleId, affected txIds, and explanation text.

⸻

9) Charts and Graph datasets (UI-ready)

Goal: produce compact aggregates so the UI doesn’t re-crunch raw JSONL every time.

9.1 Time series dataset

charts/series.<range>.json

{
  "granularity": "day",
  "points": [
    { "t": "2026-02-01", "spend": 34.20, "income": 0, "net": -34.20 },
    { "t": "2026-02-02", "spend": 12.10, "income": 0, "net": -12.10 }
  ]
}

9.2 Category breakdown dataset

charts/category_breakdown.<YYYY-MM>.json

{
  "month": "2026-02",
  "totals": [
    { "categoryId": "groceries", "value": 221.40 },
    { "categoryId": "rent", "value": 980.00 }
  ]
}

9.3 Merchant top dataset

charts/merchant_top.<YYYY-MM>.json

{
  "month": "2026-02",
  "top": [
    { "merchant": "BILLA AG", "value": 94.50, "count": 6 },
    { "merchant": "A1 Telekom", "value": 49.99, "count": 1 }
  ]
}


⸻

10) Idempotency and dedup

Same as before, with one addition: manual entries can collide with bank entries.
If a bank tx matches a manual tx (same amount, close date, merchant similar), mark:
	•	bank tx as canonical
	•	manual tx as duplicate_candidate
Never auto-delete. Put it into the review queue.

⸻

11) Storage layout (suggested)

data/
  inbox/
  sources/
  ledger/
    transactions.jsonl
    corrections.jsonl
    daily/
    monthly/
  reports/
    daily/
    monthly/
  charts/
  alerts/
    alert_rules.json
    state.json
    events.jsonl
  rules/
    categories.json
    rules.json


⸻

12) MVP milestones (updated)

MVP-0: Skeleton
	•	doc registry + hashing
	•	manual.add (creates tx)
	•	transactions.jsonl writer

MVP-1: CSV -> Ledger
	•	1 CSV adapter end-to-end
	•	dedup + fingerprints
	•	export CSV

MVP-2: Daily reporting
	•	report.daily + rolling 7d aggregates
	•	chart series (day granularity)

MVP-3: Alerts
	•	category budgets (day/week/month)
	•	alert events log + state

MVP-4: Bills + Receipts
	•	PDF text extraction + bill parser v1
	•	OCR path + receipt parser v1
	•	link receipts to tx

MVP-5: Monthly reporting
	•	recurring detection + anomalies
	•	category/merchant datasets

⸻

13) Acceptance criteria (v1)
	•	Manual entries work and are preserved even if imperfect.
	•	Same file imported twice does not duplicate.
	•	Ledger rebuild is deterministic (incl. corrections).
	•	Daily report renders in < 1s for typical datasets.
	•	Alerts trigger deterministically and are not spammy.
	•	Chart datasets are produced and stable for UI consumption.

**Design call I’m forcing on you:** keep **transactions append-only** and record user edits as **CorrectionEvents**. If you mutate history silently, you will eventually distrust your own numbers, which defeats the entire point.

Trust Score (1–100): 94 — this is an implementation-ready spec extension; no external facts, only design choices and known failure modes.
