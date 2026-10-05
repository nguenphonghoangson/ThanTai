"use strict";
// Kết xuất biểu đồ cho Thống kê, Điểm số thuật toán và Kiểm định Backtest (dựa trên charts.js).
let numberMetric = "frequency";
const STRATEGY_COLORS = { frequency: "--series-1", recent: "--series-2", balanced: "--series-3", custom: "--series-4" };

function renderNumberChart() {
  const f = analysis.features;
  const w = f.config.hot_cold_window;
  const nums = f.numbers;
  const cats = nums.map((n) => pad2(n.number));
  const configs = {
    frequency: {
      title: "Tần suất xuất hiện toàn bộ",
      note: `Số lần xuất hiện của mỗi bóng trong ${f.n_draws} kỳ quay. Đường chuẩn: Kỳ vọng lý thuyết (${fmt(f.n_draws * f.expected_rate, 1)} lần).`,
      values: nums.map((n) => n.frequency),
      ref: { value: f.n_draws * f.expected_rate, label: `Kỳ vọng: ${fmt(f.n_draws * f.expected_rate, 1)}` },
      label: "Số lần về",
    },
    recent: {
      title: `Phong độ kỳ gần (${w} kỳ quay gần nhất)`,
      note: `Số lần xuất hiện trong ${Math.min(w, f.n_draws)} kỳ gần nhất. Đường chuẩn: Kỳ vọng lý thuyết (${fmt(Math.min(w, f.n_draws) * f.expected_rate, 1)} lần).`,
      values: nums.map((n) => n.recent[String(w)]),
      ref: { value: Math.min(w, f.n_draws) * f.expected_rate, label: `Kỳ vọng: ${fmt(Math.min(w, f.n_draws) * f.expected_rate, 1)}` },
      label: `Về trong ${w} kỳ gần`,
    },
    gap: {
      title: "Số kỳ vắng mặt (Nhịp gan hiện tại)",
      note: "Số kỳ quay liên tiếp kể từ lần xuất hiện gần nhất của mỗi bóng. Đường chuẩn: Chu kỳ nhịp trung bình lý thuyết. Lưu ý: Lô gan dài không đồng nghĩa bóng sẽ dễ về ở kỳ tới.",
      values: nums.map((n) => n.gap),
      ref: { value: f.expected_gap, label: `Nhịp TB lý thuyết: ${fmt(f.expected_gap, 1)}` },
      label: "Số kỳ chưa về",
      extra: (i) => [
        { label: "Chu kỳ TB riêng của bóng", value: `${fmt(nums[i].average_gap, 1)} kỳ` },
        { label: "Độ lệch nhịp (Gan / TB)", value: `${fmt(nums[i].gap_deviation)}×` },
      ],
    },
  };
  const c = configs[numberMetric];
  const titleEl = $("#number-chart-title");
  const noteEl = $("#number-chart-note");
  if (titleEl) titleEl.textContent = c.title;
  if (noteEl) noteEl.textContent = c.note;
  for (const b of document.querySelectorAll("#number-metric button")) {
    b.setAttribute("aria-pressed", String(b.dataset.metric === numberMetric));
  }
  const container = $("#number-chart");
  if (!container) return;
  Charts.responsive(container, () =>
    Charts.columns(container, {
      ariaLabel: c.title,
      categories: cats,
      series: [{ label: c.label, values: c.values, colorVar: "--series-1" }],
      refs: [c.ref],
      tipTitle: (i) => `Bóng số ${cats[i]}`,
      tipExtra: c.extra,
      valueFormat: (v) => String(v),
    }),
  );
}

function renderDistributionCharts() {
  const f = analysis.features;
  const s = f.sums;
  const start = s.histogram[0][0];
  const width = s.histogram[0][1] - s.histogram[0][0] + 1;
  const at = (v) => (v - start) / width - 0.5;
  const sumNote = $("#sum-chart-note");
  if (sumNote) {
    sumNote.textContent =
      `Phân bố tổng điểm các kỳ quay (khoảng chia ${width} đơn vị). Trung bình thực tế ${fmt(s.mean, 1)}, lý thuyết ${fmt(s.theoretical_mean, 1)}. ` +
      `Hai đường mốc đứt đoạn thể hiện ngưỡng bách phân vị P5 và P95.`;
  }
  const sumBox = $("#sum-chart");
  if (sumBox) {
    Charts.responsive(sumBox, () =>
      Charts.columns(sumBox, {
        ariaLabel: "Phân bố tổng điểm",
        categories: s.histogram.map(([a]) => String(a)),
        series: [{ label: "Số kỳ quay", values: s.histogram.map(([, , c]) => c), colorVar: "--series-1" }],
        vlines: [
          { at: at(s.percentiles["5"]), label: "P5 (Dưới)" },
          { at: at(s.percentiles["95"]), label: "P95 (Trên)" },
        ],
        tipTitle: (i) => `Tổng điểm từ ${s.histogram[i][0]} đến ${s.histogram[i][1]}`,
      }),
    );
  }
  const pct = (v) => `${fmt(v, 1)}%`;
  const dist = (box, d, a, b) => {
    if (!box) return;
    const k = d.counts.length - 1;
    Charts.responsive(box, () =>
      Charts.columns(box, {
        ariaLabel: `Phân bố ${a}/${b}`,
        categories: d.counts.map((_, x) => `${x}/${k - x}`),
        series: [
          { label: "Thực tế", values: d.observed_pct, colorVar: "--series-1" },
          { label: "Lý thuyết ngẫu nhiên", values: d.expected_pct, colorVar: "--series-expected" },
        ],
        yFormat: (v) => `${v}%`,
        valueFormat: pct,
        labelEvery: 1,
        tipTitle: (x) => `${x} ${a} / ${k - x} ${b}`,
        tipExtra: (x) => [{ label: "Số kỳ xuất hiện", value: `${d.counts[x]} kỳ` }],
      }),
    );
  };
  dist($("#odd-chart"), f.odd_even, "Chẵn", "Lẻ");
  dist($("#low-chart"), f.low_high, "Thấp", "Cao");
}

function renderScoreChart() {
  const box = $("#score-chart");
  if (!box || !scoring) return;
  const rows = scoring.scores;
  Charts.responsive(box, () =>
    Charts.columns(box, {
      ariaLabel: "Điểm số thuật toán từng bóng",
      categories: rows.map((r) => pad2(r.number)),
      series: [{ label: "Điểm số", values: rows.map((r) => r.score), colorVar: "--series-1" }],
      refs: [{ value: 1, label: "Mức chuẩn 1.000" }],
      yFormat: (v) => fmt(v, 1),
      valueFormat: (v) => fmt(v, 3),
      tipTitle: (i) => `Bóng số ${pad2(rows[i].number)} · Xếp hạng #${rows[i].rank}`,
      tipExtra: (i) => rows[i].components.map((c) => ({
        label: COMPONENT_LABELS[c.name] || c.name,
        value: `${c.contribution >= 0 ? "+" : ""}${fmt(c.contribution, 3)}`,
      })),
    }),
  );
}

async function renderBacktestChart(runId) {
  const box = $("#bt-chart");
  if (!box) return;
  const run = await getJson(`/api/backtests/${runId}?targets=true`);
  const targets = run.result.targets;
  if (backtestShown !== runId) return;
  if (!targets.length) {
    box.replaceChildren(el("p", { className: "muted" }, "Chưa có kỳ nào được đánh giá."));
    return;
  }
  const baseline = run.params.baseline;
  const labels = run.params.strategies.map((s) => s.label).filter((l) => l !== baseline);
  // Các kỳ đầu tiên dao động rất mạnh làm phẳng toàn bộ đồ thị về sau, nên bỏ qua burn-in nếu dữ liệu dài
  const burnIn = targets.length > 90 ? 30 : 0;
  const noteEl = $("#bt-chart-note");
  if (noteEl) {
    noteEl.textContent = burnIn ? `Đồ thị bắt đầu từ kỳ thứ ${burnIn + 1}; các kỳ đầu dao động quá lớn do mẫu thống kê còn nhỏ.` : "";
  }
  const series = labels.map((label) => {
    let sum = 0;
    const values = targets.map((t, i) => {
      sum += t.mean[label] - t.mean[baseline];
      return sum / (i + 1);
    });
    return { label, values: values.slice(burnIn), colorVar: STRATEGY_COLORS[label] || "--series-4" };
  });
  const shown = targets.slice(burnIn);
  Charts.responsive(box, () =>
    Charts.lines(box, {
      ariaLabel: "Chênh lệch tích lũy so với ngẫu nhiên",
      x: shown.map((t) => t.draw_date),
      series,
      zero: 0,
      zeroLabel: "Ngẫu nhiên (Baseline)",
      yFormat: (v) => (v === 0 ? "0" : v.toFixed(3)),
      valueFormat: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(4)}`,
      tipTitle: (i) => `${shown[i].draw_date} · Kỳ #${shown[i].draw_id} · Tích lũy ${i + burnIn + 1} kỳ`,
    }),
  );
}

function renderAnalysis() {
  const { summary: s, features: f } = analysis;
  const g = gamesByKey[f.game];
  const scopeEl = $("#stats-scope");
  if (scopeEl) {
    scopeEl.textContent = `${g.name}: Từ kỳ #${f.first_draw[0]} (${f.first_draw[1]}) đến #${f.last_draw[0]} (${f.last_draw[1]})`;
  }
  const tiles = [
    ["Tổng số kỳ quay", `${s.total_draws.toLocaleString()} kỳ`],
    ["Tổng lượt bóng đã về", `${s.total_numbers.toLocaleString()} lượt`],
    ["Tổng điểm TB / kỳ", fmt(s.average_sum, 1)],
    ["Số Lẻ trung bình / kỳ", fmt(s.average_odd)],
    ["Số Chẵn trung bình / kỳ", fmt(s.average_even)],
  ];
  const statsBox = $("#stats-summary");
  if (statsBox) {
    statsBox.replaceChildren(...tiles.map(([k, v]) =>
      el("div", { className: "stat-card" }, [
        el("dt", {}, k),
        el("dd", {}, v),
        el("span", { className: "stat-sub" }, "Thống kê thực tế")
      ])
    ));
  }
  const expGap = $("#expected-gap");
  if (expGap) expGap.textContent = fmt(f.expected_gap);
  const rwHead = $("#recent-w-head");
  if (rwHead) rwHead.textContent = `Về ${f.config.hot_cold_window} kỳ gần`;
  
  renderNumbers();
  renderCountDistribution($("#odd-even-table"), f.odd_even, "Chẵn", "Lẻ");
  renderCountDistribution($("#low-high-table"), f.low_high, "Thấp", "Cao");
  
  const lhRanges = $("#low-high-ranges");
  if (lhRanges) {
    lhRanges.textContent = `Thấp (Xỉu): ${pad2(g.low_range[0])}–${pad2(g.low_range[1])}, Cao (Tài): ${pad2(g.high_range[0])}–${pad2(g.high_range[1])}.`;
  }
  
  renderSums(f.sums);
  renderNumberChart();
  renderDistributionCharts();
  renderCombos($("#pairs-block"), $("#pairs-table"), $("#pairs-note"), f.pairs);
  renderCombos($("#triples-block"), $("#triples-table"), $("#triples-note"), f.triples);
  
  // Ẩn empty state và hiển thị khu vực thống kê
  const emptyState = $("#analysis-empty-state");
  if (emptyState) emptyState.hidden = true;
  const statsSection = $("#stats-section");
  if (statsSection) statsSection.hidden = false;
}

async function onAnalyze(silent = false) {
  const btn = $("#btn-analyze");
  const status = $("#fetch-status");
  if (btn) btn.disabled = true;
  if (!silent) {
    setStatus(status, "Đang tính toán ma trận thống kê và phân tích các kỳ quay…");
  }
  const params = new URLSearchParams({
    game: $("#game").value,
    from: $("#from").value,
    to: $("#to").value,
    window: $("#window").value,
    pairs: $("#pairs").checked,
    triples: $("#triples").checked,
  });
  try {
    const [features] = await Promise.all([getJson(`/api/analysis/features?${params}`), runScoring()]);
    analysis = features;
    renderAnalysis();
    if (!silent) {
      setStatus(status, `Đã phân tích thành công ${analysis.summary.total_draws} kỳ quay thưởng.`, "success");
      // Tự động chuyển người dùng sang Tab 2 để quan sát kết quả
      if (typeof switchTab === "function") {
        switchTab("panel-analysis");
      }
    }
  } catch (err) {
    if (!silent) {
      setStatus(status, `Lỗi phân tích: ${err.message}`, "error");
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}
