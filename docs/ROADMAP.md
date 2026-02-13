# Milestone Status (`SKILL.md`)

This file maps implementation status to the milestones defined in `SKILL.md`.

## Completion Summary

1. MVP-0: **Done**
2. MVP-1: **Done**
3. MVP-2: **Done**
4. MVP-3: **Done**
5. MVP-4: **Done**
6. MVP-5: **Done**

## Delivered Beyond Base MVP

- SQLite index layer + migration framework (`index`, `migrate` CLI/API).
- OCR controls across CLI/API:
  - provider selection (`auto|pytesseract|tesseract|openai`)
  - preprocessing toggle.
- Template-aware parsing metadata:
  - parser name/version/template
  - confidence breakdown
  - missing-field markers + review hint.
- Review workflow:
  - `review queue`, `review resolve` CLI
  - `/api/review/queue`, `/api/review/resolve`
  - web UI review table with quick category resolution.
- Expanded deterministic alert rules:
  - `category_budget`
  - `recurring_new`
  - `merchant_spike`
  - `recurring_changed`
  - `cash_heavy_day`
  - `unclassified_spend`
- Web chart rendering for:
  - spend time series
  - category breakdown
  - top merchants.
- AI analysis layer:
  - `/api/ai/analyze`
  - `ai analyze` CLI
  - local heuristic insights + optional `ollama` / `openai` narratives
  - trend + forecast datasets for web charting.
- Optional API key auth (`LEDGERFLOW_API_KEY`) + audit log (`data/meta/audit.jsonl`).
- Delivery tooling:
  - `pyproject.toml`
  - Dockerfile + `.dockerignore`
  - GitHub Actions CI (`ruff`, `mypy`, tests, CLI smoke).

## Current Gaps / Next Nice-to-Haves

- More document template packs for region-specific invoice/receipt layouts.
- Incremental chart rendering for very large datasets.
- Fine-grained RBAC and user identity model for multi-user deployments.
