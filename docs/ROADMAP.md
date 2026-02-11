# Milestone Status (`SKILL.md`)

This file maps the implementation in this repo to the milestones defined in `SKILL.md`.

## Completion Summary

1. MVP-0: **Done**
2. MVP-1: **Done**
3. MVP-2: **Done**
4. MVP-3: **Done**
5. MVP-4: **Done** (best-effort parsing; OCR/PDF backends depend on optional deps/system tools)
6. MVP-5: **Done**

## Details

## MVP-0: Skeleton

- doc registry + hashing: `sources register`, `data/sources/index.json`
- manual add: `manual add`, `manual bulk-add`
- transactions writer: append-only `data/ledger/transactions.jsonl`

## MVP-1: CSV -> Ledger

- generic CSV adapter with inference + explicit column mapping
- idempotent import per source hash/doc
- CSV export endpoint/CLI (`export csv`)

## MVP-2: Daily reporting

- deterministic build step (`build`) generating daily/monthly caches
- daily report (`report daily`) with rolling 7-day aggregates + review queue
- day-granularity chart series dataset (`charts series`)

## MVP-3: Alerts

- category budget rules
- recurring_new heuristic rule
- append-only alert events log + persistent alert state

## MVP-4: Bills + Receipts

- receipt/bill import and parse (`import receipt`, `import bill`)
- extraction methods:
  - text files: native
  - PDF: `pdfplumber`/`pypdf` when installed
  - image OCR: `pytesseract` or system `tesseract`
- receipt/bill linking to bank transactions via correction events (`link receipts`, `link bills`)
- explicit OCR CLI/API: `ocr doctor`, `ocr extract`, `/api/ocr/*`

## MVP-5: Monthly reporting

- monthly report with:
  - category breakdown
  - top merchants
  - recurring detection
  - subscription drift fields
  - category + merchant spikes
  - manual/imported source mix
- monthly chart datasets:
  - category breakdown
  - merchant top

## Remaining Enhancements (Non-blocking)

- stronger parser accuracy for diverse real-world bill/receipt templates
- richer web dashboards (charts rendering, review workflow)
- durable indexing backend (SQLite) for very large datasets
- authentication for non-localhost deployments

