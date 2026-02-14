from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ledgerflow.alert_delivery import deliver_alert_events, list_outbox_entries, load_delivery_state
from ledgerflow.bootstrap import init_data_layout
from ledgerflow.layout import layout_for
from ledgerflow.storage import append_jsonl


def _event(event_id: str, *, at: str = "2026-02-10T00:00:00Z") -> dict:
    return {
        "eventId": event_id,
        "ruleId": "test_rule",
        "type": "category_budget",
        "period": "day",
        "periodKey": "2026-02-10",
        "scopeDate": "2026-02-10",
        "at": at,
        "data": {"limit": "10", "value": "20"},
        "message": "test",
    }


class TestAlertDelivery(unittest.TestCase):
    def test_outbox_delivery_is_idempotent_with_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)

            append_jsonl(layout.alerts_dir / "events.jsonl", _event("alrt_1"))
            append_jsonl(layout.alerts_dir / "events.jsonl", _event("alrt_2"))

            first = deliver_alert_events(layout, limit=100, dry_run=False)
            self.assertEqual(first["delivered"], 2)
            self.assertEqual(first["failed"], 0)

            outbox = list_outbox_entries(layout, limit=10)
            self.assertEqual(len(outbox), 2)
            self.assertEqual(outbox[-1].get("eventId"), "alrt_2")

            second = deliver_alert_events(layout, limit=100, dry_run=False)
            self.assertEqual(second["delivered"], 0)
            self.assertEqual(second["failed"], 0)
            self.assertEqual(len(list_outbox_entries(layout, limit=10)), 2)

            state = load_delivery_state(layout)
            local = ((state.get("channels") or {}).get("local_outbox") or {})
            self.assertEqual(int(local.get("cursor") or 0), 2)

    def test_delivery_dry_run_does_not_write_state_or_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)
            append_jsonl(layout.alerts_dir / "events.jsonl", _event("alrt_1"))

            out = deliver_alert_events(layout, limit=100, dry_run=True)
            self.assertTrue(out["dryRun"])
            self.assertEqual(out["delivered"], 1)
            self.assertEqual(len(list_outbox_entries(layout, limit=10)), 0)

            state = load_delivery_state(layout)
            self.assertEqual((state.get("channels") or {}), {})

    def test_channel_filter_skips_unselected_channels(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = layout_for(Path(td) / "data")
            init_data_layout(layout, write_defaults=True)
            append_jsonl(layout.alerts_dir / "events.jsonl", _event("alrt_1"))

            out = deliver_alert_events(layout, limit=100, channel_ids=["missing"], dry_run=False)
            self.assertEqual(out["channelCount"], 0)
            self.assertEqual(out["delivered"], 0)
            self.assertEqual(len(list_outbox_entries(layout, limit=10)), 0)


if __name__ == "__main__":
    unittest.main()
