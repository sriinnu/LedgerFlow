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


def _receipt_template(lines: list[str]) -> str:
    low_lines = [ln.lower() for ln in lines]
    has_total = any("total" in ln for ln in low_lines)
    has_vat = any(("vat" in ln or "tax" in ln) for ln in low_lines)
    has_card = any(("card" in ln or "visa" in ln or "mastercard" in ln) for ln in low_lines)
    if has_total and has_vat and has_card:
        return "retail_pos_with_vat_and_card"
    if has_total and has_vat:
        return "retail_pos_with_vat"
    if has_total:
        return "simple_total_line"
    return "generic_receipt"


def _bill_template(lines: list[str], text: str) -> str:
    low_lines = [ln.lower() for ln in lines]
    has_due = any(("due date" in ln or "pay by" in ln) for ln in low_lines)
    has_invoice = bool(re.search(r"\b(invoice|bill)\s*(no|number)\b", text, re.I))
    has_meter = any(("kwh" in ln or "usage" in ln or "meter" in ln) for ln in low_lines)
    if has_due and has_invoice and has_meter:
        return "utility_invoice"
    if has_due and has_invoice:
        return "standard_invoice"
    if has_due:
        return "due_notice"
    return "generic_bill"


def _score_to_two_decimals(v: float) -> float:
    return round(v, 2)


def parse_receipt_text(text: str, *, default_currency: str = "USD") -> dict[str, Any]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    template = _receipt_template(lines)
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

    confidence_breakdown = {
        "merchant": 0.30 if merchant else 0.0,
        "date": 0.25 if date else 0.0,
        "total": 0.35 if total_amt is not None else 0.0,
        "vat": 0.10 if vat else 0.0,
    }
    confidence = sum(confidence_breakdown.values())

    missing_fields: list[str] = []
    if not merchant:
        missing_fields.append("merchant")
    if not date:
        missing_fields.append("date")
    if total_amt is None:
        missing_fields.append("total")
    needs_review = confidence < 0.75 or bool(missing_fields)

    return {
        "type": "receipt",
        "merchant": merchant,
        "date": date,
        "total": {"value": fmt_decimal(total_amt or Decimal("0")), "currency": total_ccy} if total_amt is not None else None,
        "vat": vat,
        "parser": {"name": "receipt_parser", "version": "2.0", "template": template},
        "confidenceBreakdown": {k: _score_to_two_decimals(v) for k, v in confidence_breakdown.items()},
        "confidence": _score_to_two_decimals(confidence),
        "missingFields": missing_fields,
        "needsReview": needs_review,
    }


def parse_bill_text(text: str, *, default_currency: str = "USD") -> dict[str, Any]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    template = _bill_template(lines, text)
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

    confidence_breakdown = {
        "vendor": 0.25 if vendor else 0.0,
        "amount": 0.40 if amount_due is not None else 0.0,
        "dates": 0.20 if (due_date or date) else 0.0,
        "invoiceNumber": 0.15 if invoice_no else 0.0,
    }
    confidence = sum(confidence_breakdown.values())

    missing_fields: list[str] = []
    if not vendor:
        missing_fields.append("vendor")
    if amount_due is None:
        missing_fields.append("amount")
    if not due_date and not date:
        missing_fields.append("date_or_dueDate")
    needs_review = confidence < 0.75 or bool(missing_fields)

    return {
        "type": "bill",
        "vendor": vendor,
        "date": date,
        "dueDate": due_date,
        "amount": {"value": fmt_decimal(amount_due or Decimal("0")), "currency": currency} if amount_due is not None else None,
        "references": {"invoiceNumber": invoice_no} if invoice_no else {},
        "parser": {"name": "bill_parser", "version": "2.0", "template": template},
        "confidenceBreakdown": {k: _score_to_two_decimals(v) for k, v in confidence_breakdown.items()},
        "confidence": _score_to_two_decimals(confidence),
        "missingFields": missing_fields,
        "needsReview": needs_review,
    }
