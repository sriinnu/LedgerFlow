from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .ids import new_id
from .jsonl import read_jsonl
from .layout import Layout
from .storage import append_jsonl, read_json, write_json
from .timeutil import utc_now_iso


def _default_delivery_rules() -> dict[str, Any]:
    return {
        "version": 1,
        "channels": [
            {
                "id": "local_outbox",
                "type": "outbox",
                "enabled": True,
            }
        ],
    }


def _default_delivery_state() -> dict[str, Any]:
    return {"version": 1, "channels": {}}


def load_delivery_rules(layout: Layout) -> dict[str, Any]:
    cfg = read_json(layout.alert_delivery_rules_path, _default_delivery_rules())
    if not isinstance(cfg, dict):
        cfg = _default_delivery_rules()

    channels_raw = cfg.get("channels")
    channels: list[dict[str, Any]] = []
    if isinstance(channels_raw, list):
        for i, row in enumerate(channels_raw, start=1):
            if not isinstance(row, dict):
                continue
            channel = dict(row)
            channel_id = str(channel.get("id") or f"channel{i}").strip()
            if not channel_id:
                channel_id = f"channel{i}"
            channel_type = str(channel.get("type") or "outbox").strip().lower()
            if not channel_type:
                channel_type = "outbox"
            channel["id"] = channel_id
            channel["type"] = channel_type
            channel["enabled"] = bool(channel.get("enabled") if "enabled" in channel else True)
            channels.append(channel)

    cfg["channels"] = channels
    cfg["version"] = int(cfg.get("version") or 1)
    return cfg


def load_delivery_state(layout: Layout) -> dict[str, Any]:
    state = read_json(layout.alert_delivery_state_path, _default_delivery_state())
    if not isinstance(state, dict):
        return _default_delivery_state()
    if not isinstance(state.get("channels"), dict):
        state["channels"] = {}
    state["version"] = int(state.get("version") or 1)
    return state


def save_delivery_state(layout: Layout, state: dict[str, Any]) -> None:
    write_json(layout.alert_delivery_state_path, state)


def list_outbox_entries(layout: Layout, *, limit: int = 50) -> list[dict[str, Any]]:
    return read_jsonl(layout.alert_outbox_path, limit=limit)


def _to_cursor(value: Any, *, max_value: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = 0
    if n < 0 or n > max_value:
        return 0
    return n


def _delivery_payload(channel: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "deliveryId": new_id("adel"),
        "channelId": str(channel.get("id") or ""),
        "channelType": str(channel.get("type") or ""),
        "eventId": str(event.get("eventId") or ""),
        "deliveredAt": utc_now_iso(),
        "event": event,
    }


def _deliver_to_channel(layout: Layout, channel: dict[str, Any], event: dict[str, Any]) -> None:
    channel_type = str(channel.get("type") or "").strip().lower()
    payload = _delivery_payload(channel, event)

    if channel_type == "outbox":
        append_jsonl(layout.alert_outbox_path, payload)
        return

    if channel_type == "stdout":
        print(json.dumps(payload, ensure_ascii=False))
        return

    if channel_type == "webhook":
        url = str(channel.get("url") or "").strip()
        if not url:
            raise ValueError("webhook channel requires url")

        headers = {"Content-Type": "application/json"}
        raw_headers = channel.get("headers")
        if isinstance(raw_headers, dict):
            for k, v in raw_headers.items():
                key = str(k).strip()
                if not key:
                    continue
                headers[key] = str(v)

        timeout = float(channel.get("timeoutSeconds") or 10.0)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = int(resp.getcode() or 0)
                if code < 200 or code >= 300:
                    raise ValueError(f"webhook returned status {code}")
        except urllib.error.URLError as e:
            raise ValueError(f"webhook request failed: {e}") from e
        return

    raise ValueError(f"unsupported delivery channel type: {channel_type}")


def deliver_alert_events(
    layout: Layout,
    *,
    limit: int = 100,
    channel_ids: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    cfg = load_delivery_rules(layout)
    state = load_delivery_state(layout)
    events = read_jsonl(layout.alerts_dir / "events.jsonl", limit=None)

    wanted_ids: set[str] = set()
    if channel_ids:
        wanted_ids = {str(x).strip() for x in channel_ids if str(x).strip()}

    channels = [
        row
        for row in (cfg.get("channels") or [])
        if isinstance(row, dict) and bool(row.get("enabled", True)) and ((not wanted_ids) or (str(row.get("id") or "") in wanted_ids))
    ]

    results: list[dict[str, Any]] = []
    total_delivered = 0
    total_failed = 0
    channel_state = state.setdefault("channels", {})
    now = utc_now_iso()

    for channel in channels:
        channel_id = str(channel.get("id") or "")
        cursor_before = _to_cursor((channel_state.get(channel_id) or {}).get("cursor"), max_value=len(events))
        pending_all = events[cursor_before:]
        pending = pending_all
        if limit >= 0:
            pending = pending_all[:limit]

        delivered = 0
        failed = 0
        error: str | None = None

        for event in pending:
            try:
                if not dry_run:
                    _deliver_to_channel(layout, channel, event)
                delivered += 1
            except Exception as e:
                failed = 1
                error = str(e)
                break

        cursor_after = cursor_before + delivered
        total_delivered += delivered
        total_failed += failed

        result = {
            "channelId": channel_id,
            "channelType": str(channel.get("type") or ""),
            "cursorBefore": cursor_before,
            "cursorAfter": cursor_after,
            "pending": len(pending),
            "delivered": delivered,
            "failed": failed,
            "error": error,
        }
        results.append(result)

        if not dry_run:
            row = channel_state.get(channel_id) if isinstance(channel_state.get(channel_id), dict) else {}
            row = dict(row or {})
            row["cursor"] = cursor_after
            row["updatedAt"] = now
            if delivered > 0 and delivered <= len(pending):
                row["lastDeliveredEventId"] = str((pending[delivered - 1] or {}).get("eventId") or "")
                row["lastDeliveredAt"] = now
            if error:
                row["lastError"] = error
                row["lastFailedAt"] = now
            else:
                row["lastError"] = None
            channel_state[channel_id] = row

    if not dry_run:
        state["lastRun"] = now
        save_delivery_state(layout, state)

    return {
        "dryRun": dry_run,
        "eventCount": len(events),
        "channelCount": len(channels),
        "channels": results,
        "delivered": total_delivered,
        "failed": total_failed,
    }
