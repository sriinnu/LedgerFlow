async function apiGet(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function apiPostJson(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data && data.detail ? data.detail : `${res.status} ${res.statusText}`;
    throw new Error(msg);
  }
  return data;
}

async function apiPostForm(path, formData) {
  const res = await fetch(path, { method: "POST", body: formData });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data && data.detail ? data.detail : `${res.status} ${res.statusText}`;
    throw new Error(msg);
  }
  return data;
}

function setPill(ok, text, meta) {
  const pill = document.getElementById("health-pill");
  const metaEl = document.getElementById("health-meta");
  pill.textContent = text;
  pill.classList.toggle("ok", ok);
  pill.classList.toggle("bad", !ok);
  metaEl.textContent = meta || "";
}

function todayIso() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function fmtAmount(tx) {
  if (!tx.amount) return "";
  const v = tx.amount.value;
  if (typeof v === "string") return v;
  if (typeof v === "number") return v.toFixed(2);
  return "";
}

function renderTxTable(items) {
  const tbody = document.querySelector("#tx-table tbody");
  tbody.innerHTML = "";

  for (const tx of items.slice().reverse()) {
    const tr = document.createElement("tr");
    const catId = tx.category && tx.category.id ? tx.category.id : "";
    const src = tx.source && tx.source.sourceType ? tx.source.sourceType : "";
    const desc = tx.description || "";
    const merchant = tx.merchant || "";
    const date = tx.occurredAt || tx.postedAt || "";
    const ccy = tx.amount && tx.amount.currency ? tx.amount.currency : "";
    const amt = fmtAmount(tx);

    tr.innerHTML = `
      <td>${escapeHtml(date)}</td>
      <td>${escapeHtml(amt)}</td>
      <td>${escapeHtml(ccy)}</td>
      <td>${escapeHtml(merchant)}</td>
      <td>${escapeHtml(desc)}</td>
      <td>${escapeHtml(catId)}</td>
      <td>${escapeHtml(src)}</td>
    `;
    tbody.appendChild(tr);
  }
}

function renderReviewQueue(items) {
  const tbody = document.querySelector("#review-table tbody");
  tbody.innerHTML = "";

  for (const item of items) {
    const kind = item.kind || "";
    const date = item.date || "";
    const id = kind === "transaction" ? item.txId || "" : item.docId || "";
    const name = kind === "transaction" ? item.merchant || "" : item.sourceType || "";
    const reasons = Array.isArray(item.reasons) ? item.reasons.join(", ") : "";

    let actionCell = "-";
    if (kind === "transaction" && id) {
      actionCell = `
        <div class="inline">
          <input type="text" data-role="set-category" data-txid="${escapeHtml(id)}" placeholder="set category" />
          <button data-role="resolve-category" data-txid="${escapeHtml(id)}" type="button">Apply</button>
        </div>
      `;
    }

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(kind)}</td>
      <td>${escapeHtml(date)}</td>
      <td>${escapeHtml(id)}</td>
      <td>${escapeHtml(name)}</td>
      <td>${escapeHtml(reasons)}</td>
      <td>${actionCell}</td>
    `;
    tbody.appendChild(tr);
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function refresh() {
  const limit = parseInt(document.getElementById("tx-limit").value || "50", 10);
  const data = await apiGet(`/api/transactions?limit=${encodeURIComponent(limit)}`);
  renderTxTable(data.items || []);
}

async function refreshReviewQueue() {
  const out = document.getElementById("review-result");
  const date = document.getElementById("review-date").value || "";
  const params = new URLSearchParams();
  params.set("limit", "200");
  if (date) params.set("date", date);
  out.textContent = "working...";
  try {
    const data = await apiGet(`/api/review/queue?${params.toString()}`);
    renderReviewQueue(data.items || []);
    const c = data.counts || {};
    out.textContent = `transactions=${c.transactions || 0} sourceParses=${c.sourceParses || 0}`;
  } catch (e) {
    out.textContent = `error: ${String(e.message || e)}`;
  }
}

function toNum(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function clearCanvas(canvas) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  return ctx;
}

let chartsRefreshPromise = null;
let aiRefreshPromise = null;
let automationRefreshPromise = null;

function setButtonBusy(buttonId, busy) {
  const btn = document.getElementById(buttonId);
  if (!(btn instanceof HTMLButtonElement)) return;
  btn.disabled = !!busy;
  btn.setAttribute("aria-busy", busy ? "true" : "false");
}

function buildSeriesRows(points) {
  const grouped = new Map();
  for (const p of points || []) {
    const t = String(p.t || "");
    if (!t) continue;
    const cur = grouped.get(t) || { spend: 0, income: 0, net: 0 };
    cur.spend += toNum(p.spend);
    cur.income += toNum(p.income);
    cur.net += toNum(p.net);
    grouped.set(t, cur);
  }
  return Array.from(grouped.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([t, vals]) => ({ t, ...vals }));
}

function renderSeriesSummary(points) {
  const out = document.getElementById("series-summary");
  if (!out) return;
  const rows = buildSeriesRows(points);
  if (rows.length === 0) {
    out.textContent = "No spend summary available for current range.";
    return;
  }
  const spends = rows.map((r) => r.spend);
  const total = spends.reduce((a, b) => a + b, 0);
  const avg = total / spends.length;
  const first = spends[0];
  const last = spends[spends.length - 1];
  const delta = last - first;
  const pct = first !== 0 ? (delta / Math.abs(first)) * 100 : null;
  const trendDir = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const trendPct = pct == null ? "" : ` (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)`;
  out.textContent = `${rows.length} points · total ${total.toFixed(2)} · avg ${avg.toFixed(2)} · ${rows[0].t} to ${rows[rows.length - 1].t} · trend ${trendDir}${trendPct}`;
}

function setAiSummary({ providerUsed, riskCount, lookbackMonths, fallbackNote }) {
  const providerEl = document.getElementById("ai-summary-provider");
  const risksEl = document.getElementById("ai-summary-risks");
  const lookbackEl = document.getElementById("ai-summary-lookback");
  const fallbackEl = document.getElementById("ai-summary-fallback");
  if (providerEl) providerEl.textContent = providerUsed == null ? "-" : String(providerUsed);
  if (risksEl) risksEl.textContent = riskCount == null ? "-" : String(riskCount);
  if (lookbackEl) lookbackEl.textContent = lookbackMonths == null ? "-" : String(lookbackMonths);
  if (fallbackEl) fallbackEl.textContent = fallbackNote == null ? "-" : String(fallbackNote);
}

function setAiConfidence(confidence) {
  const levelEl = document.getElementById("ai-confidence-level");
  const scoreEl = document.getElementById("ai-confidence-score");
  const reasonsEl = document.getElementById("ai-confidence-reasons");

  const level = confidence && confidence.level != null ? String(confidence.level) : "-";
  const scoreNum = confidence && confidence.score != null ? Number(confidence.score) : null;
  const scoreText = Number.isFinite(scoreNum)
    ? scoreNum.toFixed(2)
    : confidence && confidence.score != null
      ? String(confidence.score)
      : "-";
  const reasons = confidence && Array.isArray(confidence.reasons) ? confidence.reasons.map((x) => String(x)).join(", ") : "-";

  if (levelEl) levelEl.textContent = level;
  if (scoreEl) scoreEl.textContent = scoreText;
  if (reasonsEl) reasonsEl.textContent = reasons || "-";
}

function compactJson(value, maxLen = 220) {
  if (value == null) return "";
  let raw = "";
  if (typeof value === "string") {
    raw = value;
  } else {
    try {
      raw = JSON.stringify(value);
    } catch {
      raw = String(value);
    }
  }
  if (raw.length <= maxLen) return raw;
  return `${raw.slice(0, Math.max(0, maxLen - 1))}…`;
}

function formatAiRecommendations(recommendations) {
  if (!Array.isArray(recommendations) || recommendations.length === 0) {
    return "No recommendations available.";
  }
  return recommendations
    .map((row, i) => {
      const priority = String(row && row.priority ? row.priority : "n/a").toUpperCase();
      const title = String((row && (row.title || row.id)) || "Recommendation");
      const action = String((row && row.action) || "");
      const impact = String((row && row.impact) || "");
      const lines = [`${i + 1}. [${priority}] ${title}`];
      if (action) lines.push(`Action: ${action}`);
      if (impact) lines.push(`Impact: ${impact}`);
      return lines.join("\n");
    })
    .join("\n\n");
}

function formatAiEvidenceSummary(evidenceRows) {
  if (!Array.isArray(evidenceRows) || evidenceRows.length === 0) {
    return "No explainability evidence available.";
  }
  return evidenceRows
    .map((row, i) => {
      const rule = String((row && row.rule) || `evidence_${i + 1}`);
      const source = String((row && row.source) || "unknown");
      const explanation = String((row && row.explanation) || "");
      const metrics =
        row && row.metrics && typeof row.metrics === "object"
          ? Object.entries(row.metrics)
              .map(([k, v]) => `${k}=${v}`)
              .join(", ")
          : "";
      const lines = [`${i + 1}. ${rule} (${source})`];
      if (explanation) lines.push(explanation);
      if (metrics) lines.push(`metrics: ${metrics}`);
      return lines.join("\n");
    })
    .join("\n\n");
}

function formatAiSavings(rows) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return "No savings opportunities detected.";
  }
  return rows
    .map((row, i) => {
      const cat = String((row && row.categoryId) || "uncategorized");
      const current = String((row && row.currentSpend) || "0");
      const target = String((row && row.targetSpend) || "0");
      const savings = String((row && row.projectedSavings) || "0");
      const ccy = String((row && row.currency) || "");
      return `${i + 1}. ${cat}\nCurrent: ${current} ${ccy}\nTarget: ${target} ${ccy}\nProjected savings: ${savings} ${ccy}`;
    })
    .join("\n\n");
}

function renderAutomationTasks(items) {
  const tbody = document.querySelector("#automation-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  for (const task of (items || []).slice().reverse()) {
    const taskId = task && task.taskId ? String(task.taskId) : "";
    const taskType = task && task.taskType ? String(task.taskType) : "";
    const status = task && task.status ? String(task.status) : "";
    const attempts = task && task.attempts != null ? Number(task.attempts) : 0;
    const maxRetries = task && task.maxRetries != null ? Number(task.maxRetries) : 0;
    const availableAt = task && task.availableAt ? String(task.availableAt) : "";
    const updatedAt = task && task.updatedAt ? String(task.updatedAt) : "";
    const source = task && task.source ? String(task.source) : "";
    const details = task && task.error ? `error: ${String(task.error)}` : compactJson(task && task.result ? task.result : "-", 180);

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(taskId)}</td>
      <td>${escapeHtml(taskType)}</td>
      <td>${escapeHtml(status)}</td>
      <td>${escapeHtml(`${attempts}/${maxRetries}`)}</td>
      <td>${escapeHtml(availableAt)}</td>
      <td>${escapeHtml(updatedAt)}</td>
      <td>${escapeHtml(source)}</td>
      <td class="wrap">${escapeHtml(details)}</td>
    `;
    tbody.appendChild(tr);
  }
}

async function refreshAutomationTasks() {
  if (automationRefreshPromise) return automationRefreshPromise;
  const out = document.getElementById("automation-result");
  const limitEl = document.getElementById("automation-limit");
  const statusEl = document.getElementById("automation-status");
  const limitRaw = parseInt(limitEl instanceof HTMLInputElement ? limitEl.value || "12" : "12", 10);
  const limit = Number.isFinite(limitRaw) ? Math.min(200, Math.max(1, limitRaw)) : 12;
  if (limitEl instanceof HTMLInputElement) limitEl.value = String(limit);
  const status = statusEl instanceof HTMLInputElement ? statusEl.value.trim() : "";
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (status) params.set("status", status);

  setButtonBusy("automation-refresh-btn", true);
  out.textContent = "loading queue...";
  automationRefreshPromise = (async () => {
    try {
      const data = await apiGet(`/api/automation/tasks?${params.toString()}`);
      const items = data.items || [];
      renderAutomationTasks(items);
      out.textContent = `queue=${items.length}`;
    } catch (e) {
      renderAutomationTasks([]);
      out.textContent = `error: ${String(e.message || e)}`;
    } finally {
      automationRefreshPromise = null;
      setButtonBusy("automation-refresh-btn", false);
    }
  })();
  return automationRefreshPromise;
}

function drawSeriesChart(points) {
  const canvas = document.getElementById("series-canvas");
  if (!(canvas instanceof HTMLCanvasElement)) return;
  const ctx = clearCanvas(canvas);

  const rows = buildSeriesRows(points);
  const xs = rows.map((r) => r.t);
  const ys = rows.map((r) => r.spend);
  if (xs.length === 0) {
    ctx.fillStyle = "rgba(255,255,255,0.6)";
    ctx.font = "13px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.fillText("No series data.", 18, 26);
    return;
  }

  const pad = { l: 48, r: 18, t: 16, b: 28 };
  const w = canvas.width - pad.l - pad.r;
  const h = canvas.height - pad.t - pad.b;
  const yMax = Math.max(...ys, 1);

  ctx.strokeStyle = "rgba(255,255,255,0.22)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.l, pad.t);
  ctx.lineTo(pad.l, pad.t + h);
  ctx.lineTo(pad.l + w, pad.t + h);
  ctx.stroke();

  ctx.strokeStyle = "rgba(82, 183, 255, 0.9)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  xs.forEach((x, i) => {
    const px = pad.l + (i / Math.max(1, xs.length - 1)) * w;
    const py = pad.t + h - (ys[i] / yMax) * h;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.stroke();

  ctx.fillStyle = "rgba(82, 183, 255, 0.2)";
  ctx.beginPath();
  xs.forEach((x, i) => {
    const px = pad.l + (i / Math.max(1, xs.length - 1)) * w;
    const py = pad.t + h - (ys[i] / yMax) * h;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.lineTo(pad.l + w, pad.t + h);
  ctx.lineTo(pad.l, pad.t + h);
  ctx.closePath();
  ctx.fill();

  ctx.fillStyle = "rgba(255,255,255,0.8)";
  ctx.font = "12px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.fillText(`Max spend ${yMax.toFixed(2)}`, pad.l + 6, pad.t + 14);
  ctx.fillText(xs[0], pad.l, canvas.height - 8);
  ctx.fillText(xs[xs.length - 1], canvas.width - 110, canvas.height - 8);
}

function drawTopBars(canvasId, items, labelKey) {
  const canvas = document.getElementById(canvasId);
  if (!(canvas instanceof HTMLCanvasElement)) return;
  const ctx = clearCanvas(canvas);

  const rows = (items || []).slice(0, 8).map((it) => ({
    label: String(it[labelKey] || ""),
    value: toNum(it.value),
  }));
  if (rows.length === 0) {
    ctx.fillStyle = "rgba(255,255,255,0.6)";
    ctx.font = "13px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.fillText("No data.", 18, 26);
    return;
  }

  const padL = 170;
  const padR = 18;
  const top = 14;
  const rowH = 30;
  const barMaxW = canvas.width - padL - padR;
  const maxVal = Math.max(...rows.map((r) => r.value), 1);

  ctx.font = "12px ui-monospace, SFMono-Regular, Menlo, monospace";
  rows.forEach((row, i) => {
    const y = top + i * rowH;
    const w = (row.value / maxVal) * barMaxW;
    ctx.fillStyle = "rgba(82, 183, 255, 0.15)";
    ctx.fillRect(padL, y + 4, barMaxW, 18);
    ctx.fillStyle = "rgba(82, 183, 255, 0.8)";
    ctx.fillRect(padL, y + 4, w, 18);
    ctx.fillStyle = "rgba(255,255,255,0.86)";
    const label = row.label.length > 26 ? `${row.label.slice(0, 25)}…` : row.label;
    ctx.fillText(label, 10, y + 18);
    ctx.fillText(row.value.toFixed(2), padL + Math.min(w + 8, barMaxW - 50), y + 18);
  });
}

async function refreshCharts() {
  if (chartsRefreshPromise) return chartsRefreshPromise;
  const out = document.getElementById("charts-result");
  const fromDate = document.getElementById("charts-from").value;
  const toDate = document.getElementById("charts-to").value;
  const month = (document.getElementById("charts-month").value || "").trim();

  setButtonBusy("charts-refresh-btn", true);
  out.textContent = "working...";
  chartsRefreshPromise = (async () => {
    try {
      const [series, monthData] = await Promise.all([
        apiPostJson("/api/charts/series", { fromDate, toDate }),
        apiPostJson("/api/charts/month", { month, limit: 12 }),
      ]);
      const seriesPoints = (series.data || {}).points || [];
      drawSeriesChart(seriesPoints);
      renderSeriesSummary(seriesPoints);
      drawTopBars("category-canvas", (monthData.categoryBreakdown || {}).totals || [], "categoryId");
      drawTopBars("merchant-canvas", (monthData.merchantTop || {}).top || [], "merchant");
      const points = seriesPoints.length;
      const cats = ((monthData.categoryBreakdown || {}).totals || []).length;
      const merchants = ((monthData.merchantTop || {}).top || []).length;
      out.textContent = `points=${points} categories=${cats} merchants=${merchants}`;
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
      renderSeriesSummary([]);
    } finally {
      chartsRefreshPromise = null;
      setButtonBusy("charts-refresh-btn", false);
    }
  })();
  return chartsRefreshPromise;
}

function drawAiForecast(historyPoints, forecastPoints) {
  const canvas = document.getElementById("ai-forecast-canvas");
  if (!(canvas instanceof HTMLCanvasElement)) return;
  const ctx = clearCanvas(canvas);

  const history = (historyPoints || []).map((p) => ({ month: String(p.month || ""), spend: toNum(p.spend) })).filter((p) => p.month);
  const forecast = (forecastPoints || [])
    .map((p) => ({ month: String(p.month || ""), spend: toNum(p.projectedSpend) }))
    .filter((p) => p.month);

  const all = [...history, ...forecast];
  if (all.length === 0) {
    ctx.fillStyle = "rgba(255,255,255,0.6)";
    ctx.font = "13px ui-monospace, SFMono-Regular, Menlo, monospace";
    ctx.fillText("No trend data.", 18, 26);
    return;
  }

  const pad = { l: 64, r: 22, t: 34, b: 44 };
  const w = canvas.width - pad.l - pad.r;
  const h = canvas.height - pad.t - pad.b;
  const labels = all.map((p) => p.month);
  const vals = all.map((p) => p.spend);
  const yMax = Math.max(...vals, 1);

  const xFor = (i) => pad.l + (i / Math.max(1, labels.length - 1)) * w;
  const yFor = (v) => pad.t + h - (v / yMax) * h;
  const yTicks = 4;

  ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
  for (let i = 0; i <= yTicks; i += 1) {
    const y = pad.t + (i / yTicks) * h;
    const tickVal = yMax - (i / yTicks) * yMax;
    ctx.strokeStyle = i === yTicks ? "rgba(255,255,255,0.22)" : "rgba(255,255,255,0.12)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(pad.l + w, y);
    ctx.stroke();
    ctx.fillStyle = "rgba(255,255,255,0.58)";
    ctx.textAlign = "left";
    ctx.fillText(tickVal.toFixed(0), 8, y + 3);
  }
  ctx.strokeStyle = "rgba(255,255,255,0.22)";
  ctx.beginPath();
  ctx.moveTo(pad.l, pad.t);
  ctx.lineTo(pad.l, pad.t + h);
  ctx.stroke();

  if (history.length > 0) {
    ctx.strokeStyle = "rgba(82, 183, 255, 0.95)";
    ctx.lineWidth = 2;
    ctx.setLineDash([]);
    ctx.beginPath();
    history.forEach((p, i) => {
      const x = xFor(i);
      const y = yFor(p.spend);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = "rgba(82, 183, 255, 0.95)";
    history.forEach((p, i) => {
      ctx.beginPath();
      ctx.arc(xFor(i), yFor(p.spend), 2.4, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  if (forecast.length > 0) {
    ctx.strokeStyle = "rgba(134, 255, 168, 0.95)";
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 6]);
    ctx.beginPath();
    const startIdx = Math.max(0, history.length - 1);
    const startVal = history.length > 0 ? history[history.length - 1].spend : forecast[0].spend;
    ctx.moveTo(xFor(startIdx), yFor(startVal));
    forecast.forEach((p, i) => {
      const x = xFor(history.length + i);
      const y = yFor(p.spend);
      ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(134, 255, 168, 0.95)";
    forecast.forEach((p, i) => {
      const x = xFor(history.length + i);
      const y = yFor(p.spend);
      ctx.fillRect(x - 2, y - 2, 4, 4);
    });
  }

  const labelIndices = Array.from(new Set([0, Math.floor((labels.length - 1) / 2), labels.length - 1]));
  ctx.fillStyle = "rgba(255,255,255,0.78)";
  labelIndices.forEach((idx) => {
    const x = xFor(idx);
    if (idx === 0) ctx.textAlign = "left";
    else if (idx === labels.length - 1) ctx.textAlign = "right";
    else ctx.textAlign = "center";
    ctx.fillText(labels[idx], x, pad.t + h + 16);
  });

  const legendStart = Math.max(pad.l + 8, canvas.width - 220);
  const legendY = 16;
  const drawLegend = (x, color, dashed, label) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.setLineDash(dashed ? [5, 4] : []);
    ctx.beginPath();
    ctx.moveTo(x, legendY);
    ctx.lineTo(x + 22, legendY);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(255,255,255,0.82)";
    ctx.textAlign = "left";
    ctx.fillText(label, x + 28, legendY + 4);
  };
  if (history.length > 0) drawLegend(legendStart, "rgba(82, 183, 255, 0.95)", false, "History");
  if (forecast.length > 0) drawLegend(legendStart + 108, "rgba(134, 255, 168, 0.95)", true, "Forecast");

  ctx.fillStyle = "rgba(255,255,255,0.80)";
  ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.textAlign = "left";
  ctx.fillText("Y axis: spend amount", pad.l, pad.t - 16);
  ctx.textAlign = "center";
  ctx.fillText("X axis: month", pad.l + w / 2, canvas.height - 8);
  ctx.textAlign = "left";
  ctx.fillText(`Max spend ${yMax.toFixed(2)}`, pad.l + 2, pad.t - 2);
}

async function refreshAiInsights() {
  if (aiRefreshPromise) return aiRefreshPromise;
  const out = document.getElementById("ai-result");
  const month = (document.getElementById("ai-month").value || "").trim();
  const provider = document.getElementById("ai-provider").value || "auto";
  const model = (document.getElementById("ai-model").value || "").trim();
  const lookbackInput = document.getElementById("ai-lookback");
  const lookbackRaw = parseInt(lookbackInput instanceof HTMLInputElement ? lookbackInput.value || "6" : "6", 10);
  const lookback = Number.isFinite(lookbackRaw) ? Math.min(24, Math.max(1, lookbackRaw)) : 6;
  if (lookbackInput instanceof HTMLInputElement) lookbackInput.value = String(lookback);
  const narrativeEl = document.getElementById("ai-narrative");
  const insightsEl = document.getElementById("ai-insights");
  const recommendationsEl = document.getElementById("ai-recommendations");
  const savingsEl = document.getElementById("ai-savings");
  const evidenceEl = document.getElementById("ai-evidence");

  setButtonBusy("ai-run-btn", true);
  out.textContent = "working...";
  aiRefreshPromise = (async () => {
    try {
      const data = await apiPostJson("/api/ai/analyze", {
        month,
        provider,
        model: model || null,
        lookbackMonths: lookback,
      });
      const insights = data.insights || [];
      narrativeEl.value = data.narrative || "";
      insightsEl.value = insights.map((x, i) => `${i + 1}. ${x}`).join("\n");
      if (recommendationsEl instanceof HTMLTextAreaElement) {
        recommendationsEl.value = formatAiRecommendations(data.recommendations || []);
      }
      if (savingsEl instanceof HTMLTextAreaElement) {
        savingsEl.value = formatAiSavings(data.savingsOpportunities || []);
      }
      if (evidenceEl instanceof HTMLTextAreaElement) {
        const evidenceRows = data.explainability && Array.isArray(data.explainability.evidence) ? data.explainability.evidence : [];
        evidenceEl.value = formatAiEvidenceSummary(evidenceRows);
      }
      const ds = data.datasets || {};
      drawAiForecast(ds.monthlySpendTrend || [], ds.spendForecast || []);
      const providerUsed = data.providerUsed || "heuristic";
      const riskCount = (data.riskFlags || []).length;
      const lookbackUsed = Number.isFinite(Number(data.lookbackMonths)) ? Number(data.lookbackMonths) : lookback;
      let fallbackNote = "No fallback used.";
      if (data.llmError) {
        fallbackNote = "LLM failed; heuristic fallback used.";
      } else if (provider === "auto" && providerUsed === "heuristic") {
        fallbackNote = "Auto selected heuristic provider.";
      } else if (provider !== "auto" && providerUsed !== provider) {
        fallbackNote = `Requested ${provider}, resolved to ${providerUsed}.`;
      }
      setAiSummary({
        providerUsed,
        riskCount,
        lookbackMonths: lookbackUsed,
        fallbackNote,
      });
      setAiConfidence(data.confidence || null);
      out.textContent = `provider=${providerUsed} risks=${riskCount} lookback=${lookbackUsed}`;
    } catch (e) {
      const msg = String(e.message || e);
      setAiSummary({
        providerUsed: "-",
        riskCount: "-",
        lookbackMonths: lookback,
        fallbackNote: `Request failed: ${msg}`,
      });
      setAiConfidence(null);
      if (recommendationsEl instanceof HTMLTextAreaElement) recommendationsEl.value = "";
      if (savingsEl instanceof HTMLTextAreaElement) savingsEl.value = "";
      if (evidenceEl instanceof HTMLTextAreaElement) evidenceEl.value = "";
      out.textContent = `error: ${msg}`;
    } finally {
      aiRefreshPromise = null;
      setButtonBusy("ai-run-btn", false);
    }
  })();
  return aiRefreshPromise;
}

async function boot() {
  try {
    const h = await apiGet("/api/health");
    setPill(true, "online", `v${h.version} · dataDir=${h.dataDir}`);
  } catch (e) {
    setPill(false, "offline", String(e.message || e));
  }

  document.getElementById("refresh-btn").addEventListener("click", () => refresh().catch(console.error));
  document.getElementById("review-refresh-btn").addEventListener("click", () => refreshReviewQueue().catch(console.error));

  // Defaults
  const t = todayIso();
  const alertsAt = document.querySelector("#alerts-form input[name='at']");
  if (alertsAt && !alertsAt.value) alertsAt.value = t;
  const dailyDate = document.querySelector("#daily-report-form input[name='date']");
  if (dailyDate && !dailyDate.value) dailyDate.value = t;
  const reviewDate = document.getElementById("review-date");
  if (reviewDate && !reviewDate.value) reviewDate.value = t;
  const chartsFrom = document.getElementById("charts-from");
  const chartsTo = document.getElementById("charts-to");
  const chartsMonth = document.getElementById("charts-month");
  if (chartsFrom && !chartsFrom.value) {
    const dt = new Date();
    dt.setDate(1);
    chartsFrom.value = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-01`;
  }
  if (chartsTo && !chartsTo.value) chartsTo.value = t;
  if (chartsMonth && !chartsMonth.value) chartsMonth.value = t.slice(0, 7);
  const aiMonth = document.getElementById("ai-month");
  if (aiMonth && !aiMonth.value) aiMonth.value = t.slice(0, 7);

  document.getElementById("manual-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const occurredAt = form.occurredAt.value || null;
    const amountValue = form.amountValue.value;
    const currency = form.currency.value || "USD";
    const merchant = form.merchant.value;
    const description = form.description.value || "";
    const categoryHint = form.categoryHint.value || null;
    const tagsRaw = form.tags.value || "";
    const tags = tagsRaw
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t.length > 0);

    const payload = {
      occurredAt,
      amount: { value: amountValue, currency },
      merchant,
      description,
      categoryHint,
      tags,
      links: {},
    };

    const out = document.getElementById("manual-result");
    out.textContent = "working...";
    try {
      const res = await apiPostJson("/api/manual/add", payload);
      out.textContent = res.tx ? res.tx.txId : "ok";
      await refresh();
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("csv-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const fileInput = form.file;
    const file = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
    if (!file) return;

    const commit = form.commit.value === "true";
    const currency = form.currency.value || "USD";
    const sample = form.sample.value || "5";
    const date_format = form.date_format.value || "";

    const fd = new FormData();
    fd.append("file", file);
    fd.append("commit", String(commit));
    fd.append("currency", currency);
    fd.append("sample", String(sample));
    if (date_format) fd.append("date_format", date_format);

    const out = document.getElementById("csv-result");
    out.textContent = "working...";
    try {
      const res = await fetch("/api/import/csv-upload", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data && data.detail ? data.detail : `${res.status} ${res.statusText}`);
      out.textContent = `${data.mode} docId=${data.docId} imported=${data.imported} skipped=${data.skipped} errors=${data.errors}`;
      await refresh();
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("receipt-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const file = form.file.files && form.file.files[0] ? form.file.files[0] : null;
    if (!file) return;
    const out = document.getElementById("receipt-result");
    out.textContent = "working...";
    const fd = new FormData();
    fd.append("file", file);
    fd.append("currency", form.currency.value || "USD");
    fd.append("copy_into_sources", form.copy_into_sources.value);
    try {
      const data = await apiPostForm("/api/import/receipt-upload", fd);
      out.textContent = `docId=${data.docId} conf=${data.parse && data.parse.confidence != null ? data.parse.confidence : "?"}`;
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("bill-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const file = form.file.files && form.file.files[0] ? form.file.files[0] : null;
    if (!file) return;
    const out = document.getElementById("bill-result");
    out.textContent = "working...";
    const fd = new FormData();
    fd.append("file", file);
    fd.append("currency", form.currency.value || "USD");
    fd.append("copy_into_sources", form.copy_into_sources.value);
    try {
      const data = await apiPostForm("/api/import/bill-upload", fd);
      out.textContent = `docId=${data.docId} conf=${data.parse && data.parse.confidence != null ? data.parse.confidence : "?"}`;
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("build-btn").addEventListener("click", async () => {
    const out = document.getElementById("build-result");
    out.textContent = "working...";
    try {
      const data = await apiPostJson("/api/build", {});
      const s = data.summary || {};
      out.textContent = `days=${(s.days || []).length} months=${(s.months || []).length} corrections=${s.appliedCorrections || 0}`;
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("alerts-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const at = form.at.value || todayIso();
    const commit = form.commit.value === "true";
    const out = document.getElementById("alerts-result");
    out.textContent = "working...";
    try {
      const data = await apiPostJson("/api/alerts/run", { at, commit });
      out.textContent = `events=${data.eventCount || 0} (${commit ? "commit" : "dry-run"})`;
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("link-receipts-btn").addEventListener("click", async () => {
    const out = document.getElementById("link-result");
    out.textContent = "working...";
    try {
      const data = await apiPostJson("/api/link/receipts", { commit: true });
      out.textContent = `receipts linked: created=${data.created || 0} attempted=${data.attempted || 0}`;
      await refresh();
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("link-bills-btn").addEventListener("click", async () => {
    const out = document.getElementById("link-result");
    out.textContent = "working...";
    try {
      const data = await apiPostJson("/api/link/bills", { commit: true });
      out.textContent = `bills linked: created=${data.created || 0} attempted=${data.attempted || 0}`;
      await refresh();
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("export-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const out = document.getElementById("export-result");
    out.textContent = "working...";
    try {
      const body = {
        fromDate: form.fromDate.value || null,
        toDate: form.toDate.value || null,
      };
      const res = await fetch("/api/export/csv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "transactions.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      out.textContent = "downloaded transactions.csv";
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  const preview = document.getElementById("report-preview");

  document.getElementById("daily-report-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const date = form.date.value || todayIso();
    const out = document.getElementById("daily-report-result");
    out.textContent = "working...";
    try {
      await apiPostJson("/api/report/daily", { date });
      out.textContent = `generated ${date}`;
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("view-daily-btn").addEventListener("click", async () => {
    const form = document.getElementById("daily-report-form");
    const date = form.date.value || todayIso();
    const out = document.getElementById("daily-report-result");
    out.textContent = "loading...";
    try {
      const res = await fetch(`/api/report/daily/${encodeURIComponent(date)}`);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const text = await res.text();
      preview.value = text;
      out.textContent = `loaded ${date}`;
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("monthly-report-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const month = (form.month.value || "").trim();
    const out = document.getElementById("monthly-report-result");
    out.textContent = "working...";
    try {
      await apiPostJson("/api/report/monthly", { month });
      out.textContent = `generated ${month}`;
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("view-monthly-btn").addEventListener("click", async () => {
    const form = document.getElementById("monthly-report-form");
    const month = (form.month.value || "").trim();
    const out = document.getElementById("monthly-report-result");
    out.textContent = "loading...";
    try {
      const res = await fetch(`/api/report/monthly/${encodeURIComponent(month)}`);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const text = await res.text();
      preview.value = text;
      out.textContent = `loaded ${month}`;
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  document.getElementById("charts-refresh-btn").addEventListener("click", async () => {
    await refreshCharts();
  });
  document.getElementById("ai-run-btn").addEventListener("click", async () => {
    await refreshAiInsights();
  });
  document.getElementById("automation-refresh-btn").addEventListener("click", async () => {
    await refreshAutomationTasks();
  });
  document.getElementById("automation-enqueue-build-btn").addEventListener("click", async () => {
    const out = document.getElementById("automation-result");
    setButtonBusy("automation-enqueue-build-btn", true);
    out.textContent = "enqueuing build...";
    try {
      const data = await apiPostJson("/api/automation/tasks", {
        taskType: "build",
        payload: {},
        maxRetries: 2,
      });
      const task = data.task || {};
      out.textContent = `queued task=${task.taskId || "-"} type=${task.taskType || "build"}`;
      await refreshAutomationTasks();
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    } finally {
      setButtonBusy("automation-enqueue-build-btn", false);
    }
  });
  document.getElementById("automation-run-due-btn").addEventListener("click", async () => {
    const out = document.getElementById("automation-result");
    setButtonBusy("automation-run-due-btn", true);
    out.textContent = "running due jobs...";
    try {
      const data = await apiPostJson("/api/automation/run-due", {});
      const created = data.created || 0;
      const skipped = Array.isArray(data.skippedJobIds) ? data.skippedJobIds.length : 0;
      out.textContent = `due jobs: created=${created} skipped=${skipped}`;
      await refreshAutomationTasks();
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    } finally {
      setButtonBusy("automation-run-due-btn", false);
    }
  });
  document.getElementById("automation-run-next-btn").addEventListener("click", async () => {
    const out = document.getElementById("automation-result");
    setButtonBusy("automation-run-next-btn", true);
    out.textContent = "running next task...";
    try {
      const data = await apiPostJson("/api/automation/run-next", {});
      if (String(data.status || "") === "idle") {
        out.textContent = "worker idle: no available tasks";
      } else {
        const task = data.task || {};
        out.textContent = `worker status=${data.status || "-"} task=${task.taskId || "-"}`;
      }
      await refreshAutomationTasks();
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    } finally {
      setButtonBusy("automation-run-next-btn", false);
    }
  });
  document.getElementById("automation-dispatch-btn").addEventListener("click", async () => {
    const out = document.getElementById("automation-result");
    setButtonBusy("automation-dispatch-btn", true);
    out.textContent = "dispatching due jobs + worker...";
    try {
      const data = await apiPostJson("/api/automation/dispatch", { runDue: true, maxTasks: 10 });
      const due = data.due || {};
      const worker = data.worker || {};
      out.textContent = `dispatch: created=${due.created || 0} processed=${worker.processed || 0} failed=${worker.failed || 0}`;
      await refreshAutomationTasks();
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    } finally {
      setButtonBusy("automation-dispatch-btn", false);
    }
  });
  document.getElementById("automation-dead-btn").addEventListener("click", async () => {
    const out = document.getElementById("automation-result");
    setButtonBusy("automation-dead-btn", true);
    out.textContent = "loading dead letters...";
    try {
      const data = await apiGet("/api/automation/dead-letters?limit=20");
      const count = data.count || 0;
      out.textContent = `dead letters=${count}`;
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    } finally {
      setButtonBusy("automation-dead-btn", false);
    }
  });

  document.querySelector("#review-table tbody").addEventListener("click", async (ev) => {
    const target = ev.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.getAttribute("data-role") !== "resolve-category") return;
    const txId = target.getAttribute("data-txid");
    if (!txId) return;
    const input = document.querySelector(`input[data-role="set-category"][data-txid="${CSS.escape(txId)}"]`);
    const category = input instanceof HTMLInputElement ? input.value.trim() : "";
    const out = document.getElementById("review-result");
    if (!category) {
      out.textContent = "error: set a category first";
      return;
    }
    out.textContent = "saving...";
    try {
      await apiPostJson("/api/review/resolve", {
        txId,
        patch: { category: { id: category, confidence: 1.0, reason: "review_resolve" } },
        reason: "review_resolve",
      });
      out.textContent = `updated ${txId}`;
      await Promise.all([refresh(), refreshReviewQueue()]);
    } catch (e) {
      out.textContent = `error: ${String(e.message || e)}`;
    }
  });

  await refreshReviewQueue();
  await refreshCharts();
  await refreshAiInsights();
  await refreshAutomationTasks();
  await refresh();
}

boot().catch(console.error);
