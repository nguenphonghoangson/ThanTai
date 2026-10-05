"use strict";
// Phân hệ Kiểm định Tịnh tiến (Walk-forward Backtest): khởi chạy, thăm dò tiến trình, kết xuất kết quả và lịch sử.
let backtestPoll = null;
let backtestShown = null;

function backtestBody() {
  const strategies = [...document.querySelectorAll("[data-bt-strategy]:checked")].map((i) => i.dataset.btStrategy);
  const body = {
    game: $("#game").value,
    start: $("#bt-from").value,
    end: $("#bt-to").value,
    training_start: $("#bt-train-from").value || null,
    strategies,
    combinations_per_draw: Number($("#bt-per-draw").value),
    min_history: Number($("#bt-min-history").value),
    step: Number($("#bt-step").value),
    base_seed: Number($("#bt-seed").value),
    window: Number($("#window").value),
    rules: generationBody(null).rules,
  };
  if ($("#bt-custom").checked) {
    const strategy = $("#strategy").value;
    const o = scoringOverrides();
    body.custom = { base: strategy === "random" ? "balanced" : strategy, weights: o.weights, intensity: o.intensity, gap_mode: o.gap_mode };
  }
  return body;
}

function renderBacktest(run) {
  backtestShown = run.id;
  const r = run.result;
  const p = run.params;
  const k = r.summary.theory.hit_pct.length - 1;
  const meta = [
    ["Giai đoạn kiểm định", `${r.first_target ?? p.start} → ${r.last_target ?? p.end}`],
    ["Số kỳ quay đã kiểm thử", `${r.n_targets} kỳ${r.skipped ? ` (${r.skipped} kỳ bỏ qua)` : ""}`],
    ["Số vé sinh mỗi kỳ", `${p.combinations_per_draw} vé / kỳ`],
    ["Hạt giống cơ sở (Seed)", p.base_seed],
    ["Lần chạy", `#${run.id} · Thời gian tính: ${fmt(r.duration_s, 1)}s`],
  ];
  const metaBox = $("#bt-meta");
  if (metaBox) {
    metaBox.replaceChildren(...meta.map(([a, b]) =>
      el("div", { className: "stat-card" }, [
        el("dt", {}, a),
        el("dd", {}, b),
        el("span", { className: "stat-sub" }, "Tham số kiểm thử")
      ])
    ));
  }

  const sig = r.summary.comparisons.filter((c) => c.significant);
  const headlineEl = $("#bt-headline");
  if (headlineEl) {
    headlineEl.textContent = r.n_targets < 30
      ? "Số lượng kỳ đánh giá quá ít (< 30 kỳ) để có kết luận thống kê đáng tin cậy."
      : sig.length
        ? `⚠️ Chú ý: Chiến lược ${sig.map((c) => c.label).join(", ")} có sự khác biệt mang ý nghĩa thống kê so với ngẫu nhiên trong đợt kiểm định này. Tuy nhiên, theo quy luật xác suất, cứ 20 lần kiểm định thì có 1 lần xuất hiện khác biệt do may rủi ngẫu nhiên: hãy thử lại với hạt giống khác và một khoảng thời gian chưa từng kiểm tra trước khi đưa ra kết luận.`
        : `✅ Kết luận khoa học: Không có chiến lược nào cho thấy sự vượt trội mang ý nghĩa thống kê so với lựa chọn ngẫu nhiên qua ${r.n_targets} kỳ quay đã đánh giá.`;
  }

  const hitHeads = Array.from({ length: k + 1 }, (_, i) => (i === 6 ? "Trúng 6 (Jackpot)" : `Trúng ${i}`));
  const head = el("thead", {}, el("tr", {}, ["Chiến lược", "Số bóng trúng TB", "Kỷ lục trúng", ...hitHeads, "Trúng giải (≥3 số)"].map((h) => el("th", {}, h))));
  const rows = Object.values(r.summary.strategies).map((m) =>
    el("tr", {}, [
      el("td", { className: "cell-bold" }, m.label),
      el("td", { className: "cell-highlight cell-bold" }, fmt(m.average_match, 4)),
      el("td", {}, m.best_match),
      ...m.hit_pct.map((x) => el("td", {}, `${fmt(x, 2)}%`)),
      el("td", { className: "cell-prize cell-bold" }, `${fmt(m.prize_rate_pct, 3)}%`),
    ]),
  );
  const t = r.summary.theory;
  rows.push(
    el("tr", { className: "theory-row", title: "Kỳ vọng toán học chính xác theo phân bố siêu bội của bộ số ngẫu nhiên đều" }, [
      el("td", { className: "text-muted" }, "Lý thuyết ngẫu nhiên đều (Uniform)"),
      el("td", { className: "text-muted" }, fmt(t.expected_average, 4)),
      el("td", {}, "—"),
      ...t.hit_pct.map((x) => el("td", { className: "text-muted" }, `${fmt(x, 2)}%`)),
      el("td", { className: "text-muted" }, `${fmt(t.prize_rate_pct, 3)}%`),
    ]),
  );
  const btTable = $("#bt-table");
  if (btTable) btTable.replaceChildren(head, el("tbody", {}, rows));

  const ci = (c) => (c.ci95[0] === null ? "—" : `[${fmt(c.ci95[0], 4)}, ${fmt(c.ci95[1], 4)}]`);
  const btCompare = $("#bt-compare");
  if (btCompare) {
    btCompare.replaceChildren(
      el("thead", {}, el("tr", {}, ["Chiến lược", "Δ so với Ngẫu nhiên", "Khoảng tin cậy 95%", "p-value", "p hiệu chỉnh (Bonferroni)", "Kết luận kiểm định"].map((h) => el("th", {}, h)))),
      el(
        "tbody",
        {},
        r.summary.comparisons.map((c) =>
          el("tr", {}, [
            el("td", { className: "cell-bold" }, c.label),
            el("td", { className: c.mean_difference > 0 ? "pos cell-bold" : c.mean_difference < 0 ? "neg" : "" }, `${c.mean_difference >= 0 ? "+" : ""}${fmt(c.mean_difference, 4)}`),
            el("td", {}, ci(c)),
            el("td", {}, fmt(c.p_value, 3)),
            el("td", { className: c.significant ? "sig cell-bold" : "" }, fmt(c.p_adjusted, 3)),
            el("td", { title: c.verdict, className: c.significant ? "cell-sig" : "" }, shortVerdict(c, r.n_targets)),
          ]),
        ),
      ),
    );
  }
  const vt = r.summary.vs_theory.random;
  const notesBox = $("#bt-notes");
  if (notesBox) {
    notesBox.replaceChildren(
      ...[
        ...(vt ? [`Kiểm tra quy chuẩn máy sinh số: Bộ đối chứng ngẫu nhiên đạt trung bình ${fmt(r.summary.strategies.random.average_match, 4)} bóng trúng so với kỳ vọng lý thuyết chính xác ${fmt(t.expected_average, 4)} (chỉ số chuẩn hóa z = ${fmt(vt.z)}).`] : []),
        ...r.notes,
      ].map((n) => el("li", {}, n)),
    );
  }
  const btCsv = $("#bt-csv");
  if (btCsv) btCsv.href = `/api/backtests/${run.id}/export.csv`;
  const btResult = $("#bt-result");
  if (btResult) btResult.hidden = false;
  
  renderBacktestChart(run.id).catch((err) => setStatus($("#bt-status"), `Lỗi vẽ biểu đồ: ${err.message}`, "error"));
  const btRuns = $("#bt-runs tbody");
  if (btRuns) {
    for (const tr of btRuns.children) {
      tr.classList.toggle("selected", Number(tr.dataset.id) === run.id);
    }
  }
}

function shortVerdict(c, n) {
  if (n < 30) return "Chưa đủ số kỳ đánh giá";
  if (!c.significant) return "Không có khác biệt (Tương đương ngẫu nhiên)";
  return `Khác biệt có ý nghĩa thống kê (${c.mean_difference > 0 ? "Tốt hơn" : "Kém hơn"})*`;
}

async function loadBacktests() {
  const gameVal = $("#game") ? $("#game").value : "mega645";
  const list = await getJson(`/api/backtests?game=${encodeURIComponent(gameVal)}&limit=20`);
  const tbody = $("#bt-runs tbody");
  if (!tbody) return;
  tbody.replaceChildren(
    ...list.map((b) => {
      const tr = el("tr", { className: b.id === backtestShown ? "selected" : "" }, [
        el("td", { className: "cell-bold" }, `#${b.id}`),
        el("td", {}, b.created_at.replace("T", " ").slice(0, 19)),
        el("td", { className: b.status === "running" ? "cell-running" : (b.status === "done" ? "cell-done" : "cell-failed") },
          b.status === "running" ? `Đang chạy (${b.progress}/${b.total})` : (b.status === "done" ? "Hoàn thành" : "Lỗi")),
        el("td", {}, `${b.start} → ${b.end}`),
        el("td", {}, b.strategies.join(", ")),
        el("td", {}, `${b.combinations_per_draw} vé`),
        el("td", {}, b.base_seed),
        el("td", { className: "cell-bold" }, b.n_targets ? `${b.n_targets} kỳ` : "–"),
      ]);
      tr.dataset.id = b.id;
      return tr;
    }),
  );
}

async function pollBacktest(id) {
  clearTimeout(backtestPoll);
  const status = $("#bt-status");
  try {
    const run = await getJson(`/api/backtests/${id}`);
    const pct = run.total ? (100 * run.progress) / run.total : 0;
    const pBar = $("#bt-progress-bar");
    if (pBar) pBar.style.width = `${pct}%`;
    if (run.status === "running") {
      setStatus(status, `Đang xử lý kiểm định… Hoàn thành ${run.progress}/${run.total || "?"} kỳ quay (${Math.round(pct)}%)`);
      backtestPoll = setTimeout(() => pollBacktest(id), 700);
      return;
    }
    const btProgress = $("#bt-progress");
    if (btProgress) btProgress.hidden = true;
    const btnBacktest = $("#btn-backtest");
    if (btnBacktest) btnBacktest.disabled = false;
    await loadBacktests();
    if (run.status === "done") {
      renderBacktest(run);
      setStatus(status, `Đã hoàn thành kiểm định #${run.id} thành công!`, "success");
    } else {
      setStatus(status, `Kiểm định #${run.id} thất bại: ${run.error}`, "error");
    }
  } catch (err) {
    const btnBacktest = $("#btn-backtest");
    if (btnBacktest) btnBacktest.disabled = false;
    setStatus(status, `Lỗi kiểm định: ${err.message}`, "error");
  }
}

async function onBacktest() {
  const status = $("#bt-status");
  const btn = $("#btn-backtest");
  if (btn) btn.disabled = true;
  setStatus(status, "Đang khởi tạo tiến trình kiểm định tịnh tiến…");
  try {
    const started = await postJson("/api/backtests", backtestBody());
    const btProgress = $("#bt-progress");
    if (btProgress) btProgress.hidden = false;
    const pBar = $("#bt-progress-bar");
    if (pBar) pBar.style.width = "0%";
    await loadBacktests();
    pollBacktest(started.id);
  } catch (err) {
    if (btn) btn.disabled = false;
    setStatus(status, `Không thể khởi chạy kiểm định: ${err.message}`, "error");
  }
}

async function onBacktestRunClick(event) {
  const tr = event.target.closest("tbody tr");
  if (!tr) return;
  try {
    const run = await getJson(`/api/backtests/${tr.dataset.id}`);
    if (run.status === "done") {
      renderBacktest(run);
      setStatus($("#bt-status"), `Đã tải kết quả kiểm định #${run.id}.`, "success");
    } else if (run.status === "running") {
      const btProgress = $("#bt-progress");
      if (btProgress) btProgress.hidden = false;
      pollBacktest(run.id);
    } else {
      setStatus($("#bt-status"), `Kiểm định #${run.id} (${run.status}): ${run.error ?? ""}`, "error");
    }
  } catch (err) {
    setStatus($("#bt-status"), `Lỗi nạp kiểm định: ${err.message}`, "error");
  }
}
