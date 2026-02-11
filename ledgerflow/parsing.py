from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from .csv_import import parse_amount_text
from .money import fmt_decimal


_RE_DATE_ISO = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
_RE_DATE_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")
_RE_DATE_DOT = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")


def _first_date(text: str) -> str | None:
    m = _RE_DATE_ISO.search(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).date().isoformat()
        except ValueError:
            pass

    m = _RE_DATE_DOT.search(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).date().isoformat()
        except ValueError:
            pass

    m = _RE_DATE_SLASH.search(text)
    if m:
        # Heuristic: assume MM/DD/YYYY (common in US exports).
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).date().isoformat()
        except ValueError:
            pass
    return None


_RE_MONEY = re.compile(
    r"(?P<ccy>USD|EUR|GBP|INR|AUD|CAD|CHF|JPY|\$|€|£)?\s*(?P<amt>\(?-?\d[\d,]*\.\d{2}\)?-?)"
)


def _find_money_candidates(line: str) -> list[tuple[str | None, Decimal]]:
    out = []
    for m in _RE_MONEY.finditer(line):
        ccy = m.group("ccy")
        raw_amt = m.group("amt")
        try:
            amt = parse_amount_text(raw_amt)
        except Exception:
            continue
        out.append((ccy, amt))
    return out


def _normalize_currency(ccy: str | None, default_currency: str) -> str:
    if not ccy:
        return default_currency
    c = ccy.strip().upper()
    if c == "$":
        return "USD"
    if c == "€":
        return "EUR"
    if c == "£":
        return "GBP"
    return c


def _guess_merchant(lines: list[str]) -> str | None:
    for ln in lines[:12]:
        s = ln.strip()
        if not s:
            continue
        low = s.lower()
        if low in ("receipt", "tax invoice", "invoice", "thank you", "thanks"):
            continue
        # Skip lines that look like addresses only.
        if re.fullmatch(r"[0-9 ,.-]+", s):
            continue
        return s[:80]
    return None


def parse_receipt_text(text: str, *, default_currency: str = "USD") -> dict[str, Any]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    merchant = _guess_merchant(lines)

    date = _first_date(text)

    total_amt: Decimal | None = None
    total_ccy: str = default_currency

    # Prefer lines with TOTAL keywords.
    total_lines = [ln for ln in lines if re.search(r"\b(total|grand total|amount due|balance due)\b", ln, re.I)]
    scan = total_lines + lines
    for ln in scan:
        cands = _find_money_candidates(ln)
        if not cands:
            continue
        # Pick largest absolute value on the line.
        ccy, amt = max(cands, key=lambda x: abs(x[1]))
        if amt is None:
            continue
        # Receipts totals are typically positive in the document.
        total_amt = abs(amt)
        total_ccy = _normalize_currency(ccy, default_currency)
        break

    vat = []
    re_vat = re.compile(r"\b(vat|tax)\b.*?(?P<rate>\d{1,2}(?:\.\d+)?)%.*?(?P<amt>\d[\d,]*\.\d{2})", re.I)
    for ln in lines:
        m = re_vat.search(ln)
        if not m:
            continue
        try:
            amt = parse_amount_text(m.group("amt"))
        except Exception:
            continue
        vat.append({"rate": m.group("rate") + "%", "amount": fmt_decimal(abs(amt))})

    confidence = 0.0
    if merchant:
        confidence += 0.3
    if date:
        confidence += 0.3
    if total_amt is not None:
        confidence += 0.4

    return {
        "type": "receipt",
        "merchant": merchant,
        "date": date,
        "total": {"value": fmt_decimal(total_amt or Decimal("0")), "currency": total_ccy} if total_amt is not None else None,
        "vat": vat,
        "confidence": round(confidence, 2),
    }


def parse_bill_text(text: str, *, default_currency: str = "USD") -> dict[str, Any]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    vendor = _guess_merchant(lines)

    date = _first_date(text)

    due_date = None
    m = re.search(r"\b(due date|pay by)\b[: ]+(?P<d>.+)$", text, re.I | re.M)
    if m:
        due_date = _first_date(m.group("d"))

    invoice_no = None
    m = re.search(r"\b(invoice|bill)\s*(no|number)\b[: ]+(?P<v>[A-Za-z0-9-]+)", text, re.I)
    if m:
        invoice_no = m.group("v")

    amount_due: Decimal | None = None
    currency = default_currency
    amount_lines = [ln for ln in lines if re.search(r"\b(amount due|total due|total)\b", ln, re.I)]
    scan = amount_lines + lines
    for ln in scan:
        cands = _find_money_candidates(ln)
        if not cands:
            continue
        ccy, amt = max(cands, key=lambda x: abs(x[1]))
        amount_due = abs(amt)
        currency = _normalize_currency(ccy, default_currency)
        break

    confidence = 0.0
    if vendor:
        confidence += 0.25
    if amount_due is not None:
        confidence += 0.4
    if due_date or date:
        confidence += 0.2
    if invoice_no:
        confidence += 0.15

    return {
        "type": "bill",
        "vendor": vendor,
        "date": date,
        "dueDate": due_date,
        "amount": {"value": fmt_decimal(amount_due or Decimal("0")), "currency": currency} if amount_due is not None else None,
        "references": {"invoiceNumber": invoice_no} if invoice_no else {},
        "confidence": round(confidence, 2),
    }

