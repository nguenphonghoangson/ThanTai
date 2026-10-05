"use strict";
// Chart rendering for statistics, scores and backtests (uses charts.js).
let numberMetric = "frequency";
const STRATEGY_COLORS = { frequency: "--series-1", recent: "--series-2", balanced: "--series-3", custom: "--series-4" };

function renderNumberChart() {
  const f = analysis.features;
  const w = f.config.hot_cold_window;
  const nums = f.numbers;
  const cats = nums.map((n) => pad2(n.number));
  const configs = {
    frequency: {
      title: "Number frequency",
      note: `Appearances per number over ${f.n_draws} draws. Line: expected count under uniform draws.`,
      values: nums.map((n) => n.frequency),
      ref: { value: f.n_draws * f.expected_rate, label: `expected ${fmt(f.n_draws * f.expected_rate, 1)}` },
      label: "appearances",
    },
    recent: {
      title: `Recent frequency (last ${w} draws)`,
      note: `Appearances in the last ${Math.min(w, f.n_draws)} draws. Line: expected count under uniform draws.`,
      values: nums.map((n) => n.recent[String(w)]),
      ref: { value: Math.min(w, f.n_draws) * f.expected_rate, label: `expected ${fmt(Math.min(w, f.n_draws) * f.expected_rate, 1)}` },
      label: `in last ${w}`,
    },
    gap: {
      title: "Current gap",
      note: "Draws since each number last appeared. Line: expected average gap under uniform draws. A long gap does not make a number more likely.",
      values: nums.map((n) => n.gap),
      ref: { value: f.expected_gap, label: `expected avg gap ${fmt(f.expected_gap, 1)}` },
      label: "draws since last seen",
      extra: (i) => [
        { label: "own average gap", value: fmt(nums[i].average_gap, 1) },
        { label: "gap / average", value: fmt(nums[i].gap_deviation) },
      ],
    },
  };
  const c = configs[numberMetric];
  $("#number-chart-title").textContent = c.title;
  $("#number-chart-note").textContent = c.note;
  for (const b of document.querySelectorAll("#number-metric button")) b.setAttribute("aria-pressed", String(b.dataset.metric === numberMetric));
  const container = $("#number-chart");
  Charts.responsive(container, () =>
    Charts.columns(container, {
      ariaLabel: c.title,
      categories: cats,
      series: [{ label: c.label, values: c.values, colorVar: "--series-1" }],
      refs: [c.ref],
      tipTitle: (i) => `Number ${cats[i]}`,
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
  $("#sum-chart-note").textContent =
    `Draws by sum of numbers (bins of ${width}). Mean ${fmt(s.mean, 1)}, theoretical ${fmt(s.theoretical_mean, 1)}. ` +
    `Lines mark P5 and P95, the default combination-filter range.`;
  const sumBox = $("#sum-chart");
  Charts.responsive(sumBox, () =>
    Charts.columns(sumBox, {
      ariaLabel: "Sum distribution",
      categories: s.histogram.map(([a]) => String(a)),
      series: [{ label: "draws", values: s.histogram.map(([, , c]) => c), colorVar: "--series-1" }],
      vlines: [
        { at: at(s.percentiles["5"]), label: "P5" },
        { at: at(s.percentiles["95"]), label: "P95" },
      ],
      tipTitle: (i) => `Sum ${s.histogram[i][0]}–${s.histogram[i][1]}`,
    }),
  );
  const pct = (v) => `${fmt(v, 1)}%`;
  const dist = (box, d, a, b) => {
    const k = d.counts.length - 1;
    Charts.responsive(box, () =>
      Charts.columns(box, {
        ariaLabel: `${a}/${b} distribution`,
        categories: d.counts.map((_, x) => `${x}/${k - x}`),
        series: [
          { label: "observed", values: d.observed_pct, colorVar: "--series-1" },
          { label: "uniform random", values: d.expected_pct, colorVar: "--series-expected" },
        ],
        yFormat: (v) => `${v}%`,
        valueFormat: pct,
        labelEvery: 1,
        tipTitle: (x) => `${x} ${a} / ${k - x} ${b}`,
        tipExtra: (x) => [{ label: "draws", value: String(d.counts[x]) }],
      }),
    );
  };
  dist($("#odd-chart"), f.odd_even, "odd", "even");
  dist($("#low-chart"), f.low_high, "low", "high");
}

function renderScoreChart() {
  const box = $("#score-chart");
  const rows = scoring.scores;
  Charts.responsive(box, () =>
    Charts.columns(box, {
      ariaLabel: "Number scores",
      categories: rows.map((r) => pad2(r.number)),
      series: [{ label: "score", values: rows.map((r) => r.score), colorVar: "--series-1" }],
      refs: [{ value: 1, label: "neutral 1.00" }],
      yFormat: (v) => fmt(v, 1),
      valueFormat: (v) => fmt(v, 3),
      tipTitle: (i) => `Number ${pad2(rows[i].number)} · rank ${rows[i].rank}`,
      tipExtra: (i) => rows[i].components.map((c) => ({
        label: COMPONENT_LABELS[c.name],
        value: `${c.contribution >= 0 ? "+" : ""}${fmt(c.contribution, 3)}`,
      })),
    }),
  );
}

async function renderBacktestChart(runId) {
  const box = $("#bt-chart");
  const run = await getJson(`/api/backtests/${runId}?targets=true`);
  const targets = run.result.targets;
  if (backtestShown !== runId) return;
  if (!targets.length) {
    box.replaceChildren(el("p", { className: "muted" }, "No draws evaluated."));
    return;
  }
  const baseline = run.params.baseline;
  const labels = run.params.strategies.map((s) => s.label).filter((l) => l !== baseline);
  // The first few running averages swing wildly and would flatten the rest of the chart.
  const burnIn = targets.length > 90 ? 30 : 0;
  $("#bt-chart-note").textContent = burnIn ? `Plotted from draw ${burnIn + 1}; earlier running averages rest on too few draws to read.` : "";
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
      ariaLabel: "Cumulative difference from random",
      x: shown.map((t) => t.draw_date),
      series,
      zero: 0,
      zeroLabel: "random",
      yFormat: (v) => (v === 0 ? "0" : v.toFixed(3)),
      valueFormat: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(4)}`,
      tipTitle: (i) => `${shown[i].draw_date} · draw #${shown[i].draw_id} · ${i + burnIn + 1} draws`,
    }),
  );
}

function renderAnalysis() {
  const { summary: s, features: f } = analysis;
  const g = gamesByKey[f.game];
  $("#stats-scope").textContent =
    `${g.name}, ${f.first_draw[1]} (#${f.first_draw[0]}) → ${f.last_draw[1]} (#${f.last_draw[0]})`;
  const tiles = [
    ["Total draws", s.total_draws.toLocaleString()],
    ["Total numbers", s.total_numbers.toLocaleString()],
    ["Average sum", fmt(s.average_sum, 1)],
    ["Average odd", fmt(s.average_odd)],
    ["Average even", fmt(s.average_even)],
  ];
  $("#stats-summary").replaceChildren(...tiles.map(([k, v]) => el("div", {}, [el("dt", {}, k), el("dd", {}, v)])));
  $("#expected-gap").textContent = fmt(f.expected_gap);
  $("#recent-w-head").textContent = `R${f.config.hot_cold_window}`;
  renderNumbers();
  renderCountDistribution($("#odd-even-table"), f.odd_even, "odd", "even");
  renderCountDistribution($("#low-high-table"), f.low_high, "low", "high");
  $("#low-high-ranges").textContent =
    `Low ${g.low_range[0]}–${g.low_range[1]}, high ${g.high_range[0]}–${g.high_range[1]}.`;
  renderSums(f.sums);
  renderNumberChart();
  renderDistributionCharts();
  renderCombos($("#pairs-block"), $("#pairs-table"), $("#pairs-note"), f.pairs);
  renderCombos($("#triples-block"), $("#triples-table"), $("#triples-note"), f.triples);
  $("#stats-section").hidden = false;
}

async function onAnalyze() {
  const btn = $("#btn-analyze");
  const status = $("#fetch-status");
  btn.disabled = true;
  setStatus(status, "Analyzing…");
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
    setStatus(status, `Analyzed ${analysis.summary.total_draws} draws.`);
  } catch (err) {
    setStatus(status, `Analysis failed: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
  }
}
