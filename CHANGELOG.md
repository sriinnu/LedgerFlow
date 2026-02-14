# Changelog

## 0.2.1 - 2026-02-14

### Added

- Alert delivery engine with cursor-based idempotency and channel routing (`outbox`, `stdout`, `webhook`).
- New alert delivery files:
  - `data/alerts/delivery_rules.json`
  - `data/alerts/delivery_state.json`
  - `data/alerts/outbox.jsonl`
- CLI surfaces:
  - `alerts deliver`
  - `alerts outbox`
- API surfaces:
  - `POST /api/alerts/deliver`
  - `GET /api/alerts/outbox`
- Automation task support for `alerts.deliver`.

### Changed

- Route-level auth now requires `automation` scope for `POST /api/alerts/deliver`.
- Ops metrics now includes `counts.alertsOutbox`.

## 0.2.0 - 2026-02-11

### Added

- SQLite index layer and schema migration framework.
- OCR backend controls (`auto|pytesseract|tesseract|openai`) across CLI and API.
- Template-aware parse metadata (`parser`, `confidenceBreakdown`, `missingFields`, `needsReview`).
- Review queue + resolve workflows in CLI/API/web.
- Expanded deterministic alert rules:
  - `merchant_spike`
  - `recurring_changed`
  - `cash_heavy_day`
  - `unclassified_spend`
- Web chart rendering for series, category breakdown, and top merchants.
- Optional API key auth mode and append-only audit logs.
- Packaging (`pyproject.toml`), Docker image, and GitHub Actions CI.
- Sample-friendly docs and onboarding improvements.

### Changed

- Default API security is now local-only when no `LEDGERFLOW_API_KEY` is set.
- Non-local API access requires API key configuration and request auth headers.

## 0.1.0 - 2026-02-10

- Initial LedgerFlow CLI/API/web implementation with ingestion, ledger, reports, alerts, and charts.
