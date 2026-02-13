from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib import error, request

from .layout import Layout
from .ledger import filter_by_month, load_ledger
from .money import fmt_decimal
from .timeutil import utc_now_iso
from .txutil import tx_amount_decimal, tx_category_confidence, tx_category_id, tx_currency, tx_merchant, tx_source_type


@dataclass(frozen=True)
class MonthRef:
    year: int
    month: int

    def as_key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def _parse_month(month: str) -> MonthRef:
    m = str(month or "").strip()
    if len(m) != 7 or m[4] != "-":
        raise ValueError("month must be in YYYY-MM format")
    year = int(m[:4])
    mon = int(m[5:7])
    if mon < 1 or mon > 12:
        raise ValueError("month must be in YYYY-MM format")
    return MonthRef(year=year, month=mon)


def _shift_month(ref: MonthRef, delta: int) -> MonthRef:
    idx = ref.year * 12 + (ref.month - 1) + delta
    year = idx // 12
    month = idx % 12 + 1
    return MonthRef(year=year, month=month)


def _month_sequence(target: MonthRef, lookback_months: int) -> list[str]:
    n = max(1, int(lookback_months))
    start = _shift_month(target, -(n - 1))
    return [_shift_month(start, i).as_key() for i in range(n)]


def _decimal_avg(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(str(len(values)))


def _decimal_abs(v: Decimal) -> Decimal:
    return v if v >= 0 else -v


def _clamp_decimal(v: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _series_by_currency(transactions: list[dict[str, Any]], months: list[str]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for month in months:
        txs = filter_by_month(transactions, month)
        by_ccy: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"spend": Decimal("0"), "income": Decimal("0"), "net": Decimal("0")})
        for tx in txs:
            ccy = tx_currency(tx) or "UNK"
            amt = tx_amount_decimal(tx)
            if amt < 0:
                by_ccy[ccy]["spend"] += -amt
            else:
                by_ccy[ccy]["income"] += amt
            by_ccy[ccy]["net"] += amt
        for ccy, vals in by_ccy.items():
            out[ccy].append(
                {
                    "month": month,
                    "spend": fmt_decimal(vals["spend"]),
                    "income": fmt_decimal(vals["income"]),
                    "net": fmt_decimal(vals["net"]),
                    "currency": ccy,
                }
            )
        if not by_ccy:
            out["UNK"].append({"month": month, "spend": "0", "income": "0", "net": "0", "currency": "UNK"})
    return dict(out)


def _choose_primary_currency(series_by_ccy: dict[str, list[dict[str, Any]]], target_month: str) -> str:
    best = "UNK"
    best_spend = Decimal("-1")
    for ccy, points in series_by_ccy.items():
        cur = next((p for p in points if p.get("month") == target_month), None)
        if not cur:
            continue
        spend = Decimal(str(cur.get("spend") or "0"))
        if spend > best_spend:
            best = ccy
            best_spend = spend
    if best_spend >= 0:
        return best
    return next(iter(series_by_ccy.keys()), "UNK")


def _top_categories_for_month(
    transactions: list[dict[str, Any]], *, month: str, currency: str, limit: int = 8
) -> list[dict[str, Any]]:
    txs = filter_by_month(transactions, month)
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for tx in txs:
        if tx_currency(tx) != currency:
            continue
        amt = tx_amount_decimal(tx)
        if amt >= 0:
            continue
        cat = tx_category_id(tx) or "uncategorized"
        totals[cat] += -amt
    rows = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"categoryId": k, "value": fmt_decimal(v), "currency": currency} for k, v in rows]


def _top_merchants_for_month(
    transactions: list[dict[str, Any]], *, month: str, currency: str, limit: int = 8
) -> list[dict[str, Any]]:
    txs = filter_by_month(transactions, month)
    totals: dict[str, dict[str, Any]] = {}
    for tx in txs:
        if tx_currency(tx) != currency:
            continue
        amt = tx_amount_decimal(tx)
        if amt >= 0:
            continue
        m = tx_merchant(tx) or "UNKNOWN"
        if m not in totals:
            totals[m] = {"value": Decimal("0"), "count": 0}
        totals[m]["value"] += -amt
        totals[m]["count"] += 1
    rows = sorted(totals.items(), key=lambda kv: kv[1]["value"], reverse=True)[:limit]
    return [{"merchant": k, "value": fmt_decimal(v["value"]), "count": int(v["count"]), "currency": currency} for k, v in rows]


def _category_trend(
    transactions: list[dict[str, Any]], *, months: list[str], currency: str, top_categories: list[str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cat in top_categories:
        points = []
        for month in months:
            txs = filter_by_month(transactions, month)
            total = Decimal("0")
            for tx in txs:
                if tx_currency(tx) != currency:
                    continue
                if (tx_category_id(tx) or "uncategorized") != cat:
                    continue
                amt = tx_amount_decimal(tx)
                if amt < 0:
                    total += -amt
            points.append({"month": month, "value": fmt_decimal(total)})
        out.append({"categoryId": cat, "currency": currency, "points": points})
    return out


def _forecast_spend(month_points: list[dict[str, Any]], *, months_forward: int = 3) -> list[dict[str, Any]]:
    vals = [Decimal(str(p.get("spend") or "0")) for p in month_points]
    months = [str(p.get("month") or "") for p in month_points]
    if not months:
        return []
    if len(vals) == 1:
        slope = Decimal("0")
    else:
        deltas = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
        slope = _decimal_avg(deltas)
    avg_spend = _decimal_avg(vals)
    avg_abs_delta = _decimal_avg([_decimal_abs(v) for v in (vals[i] - vals[i - 1] for i in range(1, len(vals)))]) if len(vals) > 1 else Decimal("0")
    volatility = Decimal("0") if avg_spend <= 0 else _clamp_decimal(avg_abs_delta / avg_spend, Decimal("0"), Decimal("1"))
    base_band_pct = _clamp_decimal(Decimal("0.08") + volatility * Decimal("0.70"), Decimal("0.08"), Decimal("0.40"))

    last_val = vals[-1]
    last_ref = _parse_month(months[-1])
    out: list[dict[str, Any]] = []
    for i in range(1, max(1, months_forward) + 1):
        m = _shift_month(last_ref, i).as_key()
        pred = last_val + slope * Decimal(str(i))
        if pred < 0:
            pred = Decimal("0")
        step_scale = Decimal("1") + Decimal(str(i - 1)) * Decimal("0.25")
        band = pred * base_band_pct * step_scale
        lower = pred - band
        if lower < 0:
            lower = Decimal("0")
        upper = pred + band
        confidence = _clamp_decimal(Decimal("1") - (base_band_pct * step_scale * Decimal("1.2")), Decimal("0.05"), Decimal("0.95"))
        out.append(
            {
                "month": m,
                "projectedSpend": fmt_decimal(pred),
                "projectedSpendLower": fmt_decimal(lower),
                "projectedSpendUpper": fmt_decimal(upper),
                "confidence": fmt_decimal(confidence),
            }
        )
    return out


def _quality_metrics(transactions: list[dict[str, Any]], *, month: str, currency: str) -> dict[str, str]:
    txs = filter_by_month(transactions, month)
    total_spend = Decimal("0")
    unclassified = Decimal("0")
    manual_spend = Decimal("0")

    for tx in txs:
        if tx_currency(tx) != currency:
            continue
        amt = tx_amount_decimal(tx)
        if amt >= 0:
            continue
        debit = -amt
        total_spend += debit
        cat = tx_category_id(tx) or "uncategorized"
        cat_conf = tx_category_confidence(tx)
        if cat in ("", "uncategorized") or cat_conf < 0.6:
            unclassified += debit
        tags = tx.get("tags") if isinstance(tx.get("tags"), list) else []
        if tx_source_type(tx) == "manual" or ("cash" in tags):
            manual_spend += debit

    unclassified_ratio = (unclassified / total_spend * Decimal("100")) if total_spend > 0 else Decimal("0")
    manual_ratio = (manual_spend / total_spend * Decimal("100")) if total_spend > 0 else Decimal("0")
    return {
        "totalSpend": fmt_decimal(total_spend),
        "unclassifiedSpend": fmt_decimal(unclassified),
        "unclassifiedPct": fmt_decimal(unclassified_ratio),
        "manualSpend": fmt_decimal(manual_spend),
        "manualPct": fmt_decimal(manual_ratio),
    }


def _heuristic_insights(*, month: str, month_points: list[dict[str, Any]], top_categories: list[dict[str, Any]], quality: dict[str, str]) -> tuple[list[str], list[str]]:
    flags: list[str] = []
    insights: list[str] = []

    target = next((p for p in month_points if p.get("month") == month), None)
    if target:
        target_spend = Decimal(str(target.get("spend") or "0"))
        prev = [Decimal(str(p.get("spend") or "0")) for p in month_points if p.get("month") != month][-3:]
        avg_prev = _decimal_avg(prev)
        if avg_prev > 0 and target_spend > avg_prev * Decimal("1.20") and (target_spend - avg_prev) > Decimal("50"):
            flags.append("spend_spike")
            insights.append(f"Spend is above the recent baseline: {fmt_decimal(target_spend)} vs avg {fmt_decimal(avg_prev)}.")
        elif avg_prev > 0:
            insights.append(f"Spend is stable versus baseline: {fmt_decimal(target_spend)} vs avg {fmt_decimal(avg_prev)}.")

    if top_categories:
        top = top_categories[0]
        insights.append(f"Top category this month is {top['categoryId']} at {top['value']} {top['currency']}.")

    unclassified_pct = Decimal(str(quality.get("unclassifiedPct") or "0"))
    manual_pct = Decimal(str(quality.get("manualPct") or "0"))
    if unclassified_pct > Decimal("12"):
        flags.append("unclassified_high")
        insights.append(f"Unclassified spend is high at {fmt_decimal(unclassified_pct)}% of debits.")
    if manual_pct > Decimal("30"):
        flags.append("manual_high")
        insights.append(f"Manual/cash-linked spend is elevated at {fmt_decimal(manual_pct)}% of debits.")

    if not insights:
        insights.append("No major risk patterns were detected in the selected month.")
    return flags, insights


def _heuristic_narrative(*, month: str, currency: str, month_points: list[dict[str, Any]], insights: list[str]) -> str:
    target = next((p for p in month_points if p.get("month") == month), {"spend": "0", "income": "0", "net": "0"})
    base = f"For {month}, spend is {target.get('spend')} {currency}, income is {target.get('income')} {currency}, net is {target.get('net')} {currency}."
    tail = " ".join(insights[:3])
    return f"{base} {tail}".strip()


def _recommendations(
    *,
    risk_flags: list[str],
    top_categories: list[dict[str, Any]],
    quality: dict[str, str],
    month: str,
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    if "spend_spike" in risk_flags and top_categories:
        top = top_categories[0]
        recs.append(
            {
                "id": "spike_review_top_category",
                "priority": "high",
                "title": f"Review top category ({top['categoryId']}) spend",
                "action": f"Set a temporary cap for {top['categoryId']} and review large debits above normal in {month}.",
                "impact": "Can reduce next-month spend drift quickly.",
            }
        )
    if "unclassified_high" in risk_flags:
        recs.append(
            {
                "id": "resolve_unclassified",
                "priority": "high",
                "title": "Resolve unclassified transactions",
                "action": "Use review queue to set categories for uncategorized transactions.",
                "impact": "Improves report quality and alert precision.",
            }
        )
    if "manual_high" in risk_flags:
        recs.append(
            {
                "id": "link_cash_receipts",
                "priority": "medium",
                "title": "Attach receipts to manual/cash spend",
                "action": "Link receipt docs and add merchant/category details for manual entries.",
                "impact": "Reduces blind spots in month-end reconciliation.",
            }
        )
    if not recs:
        recs.append(
            {
                "id": "maintain_baseline",
                "priority": "low",
                "title": "Maintain current spend controls",
                "action": "Keep recurring charges and top categories under weekly review.",
                "impact": "Helps preserve stable spend behavior.",
            }
        )
    return recs


def _analysis_confidence(
    *,
    month_points: list[dict[str, Any]],
    quality: dict[str, str],
    provider_used: str,
    llm_error: str | None,
) -> dict[str, Any]:
    score = Decimal("0.72")
    reasons: list[str] = []

    if len(month_points) < 3:
        score -= Decimal("0.12")
        reasons.append("short_history_window")
    else:
        score += Decimal("0.04")
        reasons.append("sufficient_history")

    unclassified_pct = Decimal(str(quality.get("unclassifiedPct") or "0"))
    manual_pct = Decimal(str(quality.get("manualPct") or "0"))
    if unclassified_pct > Decimal("20"):
        score -= Decimal("0.15")
        reasons.append("high_unclassified_spend")
    elif unclassified_pct < Decimal("8"):
        score += Decimal("0.05")
        reasons.append("low_unclassified_spend")

    if manual_pct > Decimal("35"):
        score -= Decimal("0.10")
        reasons.append("high_manual_ratio")

    if provider_used in ("ollama", "openai"):
        score += Decimal("0.04")
        reasons.append("llm_narrative_enrichment")
    if llm_error:
        score -= Decimal("0.06")
        reasons.append("llm_fallback_applied")

    score = _clamp_decimal(score, Decimal("0.15"), Decimal("0.98"))
    if score >= Decimal("0.80"):
        level = "high"
    elif score >= Decimal("0.60"):
        level = "medium"
    else:
        level = "low"
    return {"score": fmt_decimal(score), "level": level, "reasons": reasons}


def _build_explainability(
    *,
    month: str,
    risk_flags: list[str],
    top_categories: list[dict[str, Any]],
    quality: dict[str, str],
    summary: dict[str, Any],
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    if "spend_spike" in risk_flags:
        evidence.append(
            {
                "rule": "spend_spike",
                "source": "datasets.monthlySpendTrend",
                "explanation": f"Current month spend is materially above recent baseline for {month}.",
                "metrics": {"spend": str(summary.get("spend") or "0"), "month": month},
            }
        )
    if top_categories:
        top = top_categories[0]
        evidence.append(
            {
                "rule": "top_category",
                "source": "topCategories",
                "explanation": "Largest category contribution in selected month.",
                "metrics": {"categoryId": top.get("categoryId"), "value": str(top.get("value") or "0")},
            }
        )
    evidence.append(
        {
            "rule": "data_quality",
            "source": "quality",
            "explanation": "Coverage and confidence quality checks for categorized spend.",
            "metrics": {
                "unclassifiedPct": str(quality.get("unclassifiedPct") or "0"),
                "manualPct": str(quality.get("manualPct") or "0"),
            },
        }
    )
    return {"evidence": evidence}


def _prompt_from_context(context: dict[str, Any]) -> str:
    return (
        "You are a financial operations analyst for a local-first ledger app.\n"
        "Write concise, practical insights focused on spending control and next actions.\n"
        "Keep output under 120 words and avoid disclaimers.\n"
        "Context JSON:\n"
        + json.dumps(context, ensure_ascii=False)
    )


def _openai_generate(prompt: str, *, model: str) -> str:
    from openai import OpenAI  # type: ignore

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    resp = client.responses.create(
        model=model,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        max_output_tokens=400,
    )
    text = str(getattr(resp, "output_text", "") or "").strip()
    if not text:
        raise RuntimeError("empty output from OpenAI")
    return text


def _ollama_generate(prompt: str, *, model: str) -> str:
    url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.URLError as e:
        raise RuntimeError(f"ollama request failed: {e}") from e
    text = str(data.get("response") or "").strip()
    if not text:
        raise RuntimeError("empty output from ollama")
    return text


def _try_llm(provider: str, prompt: str, model: str) -> tuple[str | None, str | None]:
    if provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            return None, "OPENAI_API_KEY not set"
        try:
            return _openai_generate(prompt, model=model), None
        except Exception as e:
            return None, str(e)

    if provider == "ollama":
        try:
            return _ollama_generate(prompt, model=model), None
        except Exception as e:
            return None, str(e)

    return None, "unsupported provider"


def analyze_spending(
    layout: Layout,
    *,
    month: str,
    provider: str = "auto",
    model: str | None = None,
    lookback_months: int = 6,
) -> dict[str, Any]:
    target = _parse_month(month).as_key()
    months = _month_sequence(_parse_month(target), lookback_months=max(1, lookback_months))
    transactions = load_ledger(layout, include_deleted=False).transactions
    series_by_ccy = _series_by_currency(transactions, months)
    primary_currency = _choose_primary_currency(series_by_ccy, target)
    month_points = series_by_ccy.get(primary_currency, [])

    top_categories = _top_categories_for_month(transactions, month=target, currency=primary_currency, limit=8)
    top_merchants = _top_merchants_for_month(transactions, month=target, currency=primary_currency, limit=8)
    category_ids = [row["categoryId"] for row in top_categories[:5]]
    quality = _quality_metrics(transactions, month=target, currency=primary_currency)
    risk_flags, insights = _heuristic_insights(month=target, month_points=month_points, top_categories=top_categories, quality=quality)
    heuristic_narrative = _heuristic_narrative(month=target, currency=primary_currency, month_points=month_points, insights=insights)
    forecast = _forecast_spend(month_points, months_forward=3)
    cat_trend = _category_trend(transactions, months=months, currency=primary_currency, top_categories=category_ids)

    summary = next((p for p in month_points if p.get("month") == target), {})
    recommendations = _recommendations(risk_flags=risk_flags, top_categories=top_categories, quality=quality, month=target)

    context = {
        "month": target,
        "currency": primary_currency,
        "summary": summary,
        "topCategories": top_categories[:5],
        "topMerchants": top_merchants[:5],
        "riskFlags": risk_flags,
        "quality": quality,
        "insights": insights,
        "recommendations": recommendations[:3],
    }
    prompt = _prompt_from_context(context)

    requested = str(provider or "auto").strip().lower()
    used = "heuristic"
    llm_error = None
    narrative = heuristic_narrative

    if requested not in ("auto", "heuristic", "ollama", "openai"):
        raise ValueError("provider must be one of: auto, heuristic, ollama, openai")

    if requested == "openai":
        model_name = model or "gpt-4.1-mini"
        text, err = _try_llm("openai", prompt, model_name)
        if text:
            narrative = text
            used = "openai"
        else:
            llm_error = err
    elif requested == "ollama":
        model_name = model or os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        text, err = _try_llm("ollama", prompt, model_name)
        if text:
            narrative = text
            used = "ollama"
        else:
            llm_error = err
    elif requested == "auto":
        model_ollama = model or os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        text, err = _try_llm("ollama", prompt, model_ollama)
        if text:
            narrative = text
            used = "ollama"
        else:
            model_openai = model or "gpt-4.1-mini"
            text2, err2 = _try_llm("openai", prompt, model_openai)
            if text2:
                narrative = text2
                used = "openai"
            else:
                llm_error = f"ollama: {err}; openai: {err2}"

    explainability = _build_explainability(
        month=target,
        risk_flags=risk_flags,
        top_categories=top_categories,
        quality=quality,
        summary=summary,
    )
    confidence = _analysis_confidence(
        month_points=month_points,
        quality=quality,
        provider_used=used,
        llm_error=llm_error,
    )

    return {
        "month": target,
        "generatedAt": utc_now_iso(),
        "providerRequested": requested,
        "providerUsed": used,
        "model": model,
        "currency": primary_currency,
        "summary": next((p for p in month_points if p.get("month") == target), {"month": target, "spend": "0", "income": "0", "net": "0"}),
        "quality": quality,
        "topCategories": top_categories,
        "topMerchants": top_merchants,
        "riskFlags": risk_flags,
        "insights": insights,
        "recommendations": recommendations,
        "confidence": confidence,
        "explainability": explainability,
        "narrative": narrative,
        "datasets": {
            "monthlySpendTrend": month_points,
            "categoryTrend": cat_trend,
            "spendForecast": forecast,
        },
        "llmError": llm_error,
    }
