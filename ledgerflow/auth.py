from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any


_DEFAULT_RW_SCOPES = {"read", "write"}


def _parse_scopes(value: Any) -> set[str]:
    if isinstance(value, str):
        scopes = {x.strip() for x in value.split(",") if x.strip()}
    elif isinstance(value, list):
        scopes = {str(x).strip() for x in value if str(x).strip()}
    else:
        scopes = set()
    if "admin" in scopes:
        scopes.update(_DEFAULT_RW_SCOPES)
    return scopes


def load_api_key_store_from_env() -> dict[str, dict[str, Any]]:
    """
    Loads key configuration from environment.

    Supported variables:
    - LEDGERFLOW_API_KEY: single legacy full-access key
    - LEDGERFLOW_API_KEYS: JSON list/object for scoped keys

    LEDGERFLOW_API_KEYS accepted shapes:
    - list: [{"id": "reader", "key": "token", "scopes": ["read"]}, ...]
    - object: {"reader": {"key": "token", "scopes": ["read"]}, ...}
    """
    out: dict[str, dict[str, Any]] = {}

    raw_multi = (os.environ.get("LEDGERFLOW_API_KEYS") or "").strip()
    if raw_multi:
        try:
            parsed = json.loads(raw_multi)
        except Exception:
            parsed = None

        rows: list[dict[str, Any]] = []
        if isinstance(parsed, list):
            rows = [x for x in parsed if isinstance(x, dict)]
        elif isinstance(parsed, dict):
            for key_id, cfg in parsed.items():
                if isinstance(cfg, dict):
                    item = dict(cfg)
                    item.setdefault("id", str(key_id))
                    rows.append(item)

        for i, item in enumerate(rows, start=1):
            token = str(item.get("key") or "").strip()
            if not token:
                continue
            key_id = str(item.get("id") or f"key{i}").strip()
            scopes = _parse_scopes(item.get("scopes") or ["read", "write"])
            if not scopes:
                scopes = set(_DEFAULT_RW_SCOPES)
            enabled = bool(item.get("enabled") if "enabled" in item else True)
            expires_at = str(item.get("expiresAt") or "").strip() or None
            out[token] = {
                "id": key_id,
                "scopes": sorted(scopes),
                "kind": "scoped",
                "enabled": enabled,
                "expiresAt": expires_at,
            }

    legacy = str(os.environ.get("LEDGERFLOW_API_KEY") or "").strip()
    if legacy and legacy not in out:
        out[legacy] = {
            "id": "legacy",
            "scopes": sorted({"admin", *list(_DEFAULT_RW_SCOPES)}),
            "kind": "legacy",
            "enabled": True,
            "expiresAt": None,
        }

    return out


def auth_mode_for_store(store: dict[str, dict[str, Any]]) -> str:
    if not store:
        return "local_only_no_key"
    if any((meta.get("kind") == "scoped") for meta in store.values()):
        return "api_key_scoped"
    return "api_key"


def scope_for_request(method: str, path: str) -> str | None:
    m = str(method or "").upper()
    p = str(path or "")
    if not p.startswith("/api/"):
        return None
    if p == "/api/health" or m == "OPTIONS":
        return None
    if m in ("GET", "HEAD"):
        return "read"
    return "write"


def key_has_scope(meta: dict[str, Any], required: str) -> bool:
    if not bool(meta.get("enabled", True)):
        return False
    exp = _parse_expiry(meta.get("expiresAt"))
    if exp is not None and datetime.now(UTC) >= exp:
        return False

    scopes = {str(x) for x in (meta.get("scopes") or [])}
    if "admin" in scopes:
        return True
    if required == "read" and "write" in scopes:
        return True
    return required in scopes


def _parse_expiry(value: Any) -> datetime | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def scope_denial_reason(meta: dict[str, Any], required: str) -> str | None:
    if not bool(meta.get("enabled", True)):
        return "api_key_disabled"
    exp = _parse_expiry(meta.get("expiresAt"))
    if exp is not None and datetime.now(UTC) >= exp:
        return "api_key_expired"
    if key_has_scope(meta, required):
        return None
    return "insufficient_scope"
