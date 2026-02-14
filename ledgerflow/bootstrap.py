from __future__ import annotations

from .index_db import ensure_index_schema
from .layout import Layout
from .storage import ensure_dir, write_json


def init_data_layout(layout: Layout, *, write_defaults: bool = True) -> None:
    # Directories (from SKILL.md suggested layout).
    ensure_dir(layout.data_dir / "inbox")
    ensure_dir(layout.data_dir / "sources")
    ensure_dir(layout.data_dir / "ledger" / "daily")
    ensure_dir(layout.data_dir / "ledger" / "monthly")
    ensure_dir(layout.data_dir / "reports" / "daily")
    ensure_dir(layout.data_dir / "reports" / "monthly")
    ensure_dir(layout.data_dir / "charts")
    ensure_dir(layout.automation_dir)
    ensure_dir(layout.data_dir / "alerts")
    ensure_dir(layout.data_dir / "rules")
    ensure_dir(layout.index_dir)
    ensure_dir(layout.meta_dir)
    ensure_index_schema(layout.index_db_path)

    if not write_defaults:
        return

    if not layout.categories_path.exists():
        write_json(
            layout.categories_path,
            {
                "categories": [
                    {"id": "groceries", "label": "Groceries"},
                    {"id": "restaurants", "label": "Restaurants"},
                    {"id": "rent", "label": "Rent"},
                    {"id": "utilities", "label": "Utilities"},
                    {"id": "transport", "label": "Transport"},
                    {"id": "shopping", "label": "Shopping"},
                    {"id": "health", "label": "Health"},
                    {"id": "income", "label": "Income"},
                    {"id": "uncategorized", "label": "Uncategorized"},
                ]
            },
        )

    if not layout.alert_rules_path.exists():
        write_json(
            layout.alert_rules_path,
            {
                "currency": "USD",
                "rules": [
                    {
                        "id": "groceries_monthly",
                        "type": "category_budget",
                        "categoryId": "groceries",
                        "period": "month",
                        "limit": 600,
                    },
                    {
                        "id": "restaurants_weekly",
                        "type": "category_budget",
                        "categoryId": "restaurants",
                        "period": "week",
                        "limit": 120,
                    },
                    {
                        "id": "new_recurring",
                        "type": "recurring_new",
                        "minOccurrences": 3,
                        "spacingDays": [25, 35],
                    },
                    {
                        "id": "merchant_spike_monthly",
                        "type": "merchant_spike",
                        "period": "month",
                        "lookbackPeriods": 3,
                        "multiplier": 1.5,
                        "minDelta": 50,
                    },
                    {
                        "id": "recurring_changed",
                        "type": "recurring_changed",
                        "minOccurrences": 3,
                        "spacingDays": [25, 35],
                        "minDelta": 5,
                        "minDeltaPct": 5,
                    },
                    {
                        "id": "cash_heavy_day",
                        "type": "cash_heavy_day",
                        "limit": 150,
                    },
                    {
                        "id": "unclassified_spend_day",
                        "type": "unclassified_spend",
                        "period": "day",
                        "categoryConfidenceBelow": 0.6,
                        "limit": 50,
                    },
                ],
            },
        )

    if not layout.alert_delivery_rules_path.exists():
        write_json(
            layout.alert_delivery_rules_path,
            {
                "version": 1,
                "channels": [
                    {
                        "id": "local_outbox",
                        "type": "outbox",
                        "enabled": True,
                    }
                ],
            },
        )

    if not layout.alert_delivery_state_path.exists():
        write_json(
            layout.alert_delivery_state_path,
            {
                "version": 1,
                "channels": {},
            },
        )

    if not layout.automation_jobs_path.exists():
        write_json(
            layout.automation_jobs_path,
            {
                "version": 1,
                "jobs": [],
            },
        )

    if not layout.automation_queue_path.exists():
        write_json(
            layout.automation_queue_path,
            {
                "version": 1,
                "tasks": [],
            },
        )

    if not layout.automation_state_path.exists():
        write_json(
            layout.automation_state_path,
            {
                "version": 1,
                "lastSlots": {},
            },
        )
