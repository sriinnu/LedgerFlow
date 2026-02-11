# Data Layout

LedgerFlow is local-first. Everything lives under `data/` (or `--data-dir`).

This is the suggested structure from `SKILL.md` (the CLI creates it):

```
data/
  inbox/
  sources/
  ledger/
    transactions.jsonl        # append-only
    corrections.jsonl         # append-only (user edits)
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
  exports/
  rules/
    categories.json
```

## Auditability Rules

- Do not silently rewrite transaction history.
- Treat `transactions.jsonl` and `corrections.jsonl` as append-only logs.
- Derived outputs (reports/charts/daily/monthly) should be deterministically rebuildable from those logs + sources.

## Git Hygiene

Never commit raw documents or derived financial data. `.gitignore` is set up to exclude `data/**` artifacts.
