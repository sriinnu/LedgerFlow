from __future__ import annotations

import secrets
import time


_CROCKFORD32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    """
    Generate a ULID (26 chars, Crockford base32).
    Not monotonic; good enough for ids/log lines.
    """
    ts_ms = int(time.time() * 1000)
    rand = secrets.randbits(80)
    value = (ts_ms << 80) | rand  # 128 bits

    # ULID uses 26 base32 chars = 130 bits. Left-pad with 2 zeros.
    value <<= 2

    out = []
    for i in range(26):
        shift = (25 - i) * 5
        out.append(_CROCKFORD32[(value >> shift) & 0x1F])
    return "".join(out)


def new_id(prefix: str) -> str:
    return f"{prefix}_{ulid()}"

