# Changelog

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
