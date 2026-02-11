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

function drawSeriesChart(points) {
  const canvas = document.getElementById("series-canvas");
  if (!(canvas instanceof HTMLCanvasElement)) return;
  const ctx = clearCanvas(canvas);

  const grouped = new Map();
  for (const p of points) {
    const t = p.t || "";
    if (!t) continue;
    const cur = grouped.get(t) || { spend: 0, income: 0, net: 0 };
    cur.spend += toNum(p.spend);
    cur.income += toNum(p.income);
    cur.net += toNum(p.net);
    grouped.set(t, cur);
  }
  const xs = Array.from(grouped.keys()).sort();
  const ys = xs.map((x) => grouped.get(x).spend);
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
  const out = document.getElementById("charts-result");
  const fromDate = document.getElementById("charts-from").value;
  const toDate = document.getElementById("charts-to").value;
  const month = (document.getElementById("charts-month").value || "").trim();
  out.textContent = "working...";

  try {
    const [series, monthData] = await Promise.all([
      apiPostJson("/api/charts/series", { fromDate, toDate }),
      apiPostJson("/api/charts/month", { month, limit: 12 }),
    ]);
    drawSeriesChart((series.data || {}).points || []);
    drawTopBars("category-canvas", (monthData.categoryBreakdown || {}).totals || [], "categoryId");
    drawTopBars("merchant-canvas", (monthData.merchantTop || {}).top || [], "merchant");
    const points = ((series.data || {}).points || []).length;
    const cats = ((monthData.categoryBreakdown || {}).totals || []).length;
    const merchants = ((monthData.merchantTop || {}).top || []).length;
    out.textContent = `points=${points} categories=${cats} merchants=${merchants}`;
  } catch (e) {
    out.textContent = `error: ${String(e.message || e)}`;
  }
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
  await refresh();
}

boot().catch(console.error);
