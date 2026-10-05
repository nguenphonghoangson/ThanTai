"use strict";
// Walk-forward backtest runs: start, poll, render, history.
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
    ["Backtest period", `${r.first_target ?? p.start} → ${r.last_target ?? p.end}`],
    ["Draws evaluated", `${r.n_targets}${r.skipped ? ` (${r.skipped} skipped)` : ""}`],
    ["Combinations / draw", p.combinations_per_draw],
    ["Base seed", p.base_seed],
    ["Run", `#${run.id} · ${fmt(r.duration_s, 1)}s`],
  ];
  $("#bt-meta").replaceChildren(...meta.map(([a, b]) => el("div", {}, [el("dt", {}, a), el("dd", {}, b)])));

  const sig = r.summary.comparisons.filter((c) => c.significant);
  $("#bt-headline").textContent = r.n_targets < 30
    ? "Too few draws evaluated for a meaningful comparison."
    : sig.length
      ? `* ${sig.map((c) => c.label).join(", ")} differed significantly from random in this run. One run in twenty crosses this threshold by chance: re-run with another base seed and a later, untouched period before reading anything into it.`
      : `No strategy differed significantly from the random baseline over ${r.n_targets} draws.`;

  const hitHeads = Array.from({ length: k + 1 }, (_, i) => `${i} hit`);
  const head = el("thead", {}, el("tr", {}, ["Strategy", "Avg match", "Best", ...hitHeads, "≥3 hits"].map((h) => el("th", {}, h))));
  const rows = Object.values(r.summary.strategies).map((m) =>
    el("tr", {}, [
      el("td", {}, m.label),
      el("td", {}, fmt(m.average_match, 4)),
      el("td", {}, m.best_match),
      ...m.hit_pct.map((x) => el("td", {}, `${fmt(x, 2)}%`)),
      el("td", {}, `${fmt(m.prize_rate_pct, 3)}%`),
    ]),
  );
  const t = r.summary.theory;
  rows.push(
    el("tr", { className: "theory", title: "Exact expectation for uniformly random combinations" }, [
      el("td", {}, "theory (uniform)"),
      el("td", {}, fmt(t.expected_average, 4)),
      el("td", {}, ""),
      ...t.hit_pct.map((x) => el("td", {}, `${fmt(x, 2)}%`)),
      el("td", {}, `${fmt(t.prize_rate_pct, 3)}%`),
    ]),
  );
  $("#bt-table").replaceChildren(head, el("tbody", {}, rows));

  const ci = (c) => (c.ci95[0] === null ? "n/a" : `[${fmt(c.ci95[0], 4)}, ${fmt(c.ci95[1], 4)}]`);
  $("#bt-compare").replaceChildren(
    el("thead", {}, el("tr", {}, ["Strategy", "Δ vs random", "95% CI", "p", "p(adj)", "Verdict"].map((h) => el("th", {}, h)))),
    el(
      "tbody",
      {},
      r.summary.comparisons.map((c) =>
        el("tr", {}, [
          el("td", {}, c.label),
          el("td", {}, `${c.mean_difference >= 0 ? "+" : ""}${fmt(c.mean_difference, 4)}`),
          el("td", {}, ci(c)),
          el("td", {}, fmt(c.p_value, 3)),
          el("td", { className: c.significant ? "sig" : "" }, fmt(c.p_adjusted, 3)),
          el("td", { title: c.verdict }, shortVerdict(c, r.n_targets)),
        ]),
      ),
    ),
  );
  const vt = r.summary.vs_theory.random;
  $("#bt-notes").replaceChildren(
    ...[
      ...(vt ? [`Harness check: random baseline averaged ${fmt(r.summary.strategies.random.average_match, 4)} vs exact expectation ${fmt(t.expected_average, 4)} (z = ${fmt(vt.z)}).`] : []),
      ...r.notes,
    ].map((n) => el("li", {}, n)),
  );
  $("#bt-csv").href = `/api/backtests/${run.id}/export.csv`;
  $("#bt-result").hidden = false;
  renderBacktestChart(run.id).catch((err) => setStatus($("#bt-status"), `Chart failed: ${err.message}`, "error"));
  for (const tr of $("#bt-runs tbody").children) tr.classList.toggle("selected", Number(tr.dataset.id) === run.id);
}

function shortVerdict(c, n) {
  if (n < 30) return "Too few draws";
  if (!c.significant) return "No significant difference";
  return `Significantly ${c.mean_difference > 0 ? "better" : "worse"} in this run*`;
}

async function loadBacktests() {
  const list = await getJson(`/api/backtests?game=${encodeURIComponent($("#game").value)}&limit=20`);
  $("#bt-runs tbody").replaceChildren(
    ...list.map((b) => {
      const tr = el("tr", { className: b.id === backtestShown ? "selected" : "" }, [
        el("td", {}, b.id),
        el("td", {}, b.created_at.replace("T", " ").slice(0, 19)),
        el("td", {}, b.status === "running" ? `running ${b.progress}/${b.total}` : b.status),
        el("td", {}, `${b.start} → ${b.end}`),
        el("td", {}, b.strategies.join(", ")),
        el("td", {}, b.combinations_per_draw),
        el("td", {}, b.base_seed),
        el("td", {}, b.n_targets ?? "–"),
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
    $("#bt-progress-bar").style.width = `${pct}%`;
    if (run.status === "running") {
      setStatus(status, `Running… ${run.progress}/${run.total || "?"} draws`);
      backtestPoll = setTimeout(() => pollBacktest(id), 700);
      return;
    }
    $("#bt-progress").hidden = true;
    $("#btn-backtest").disabled = false;
    await loadBacktests();
    if (run.status === "done") {
      renderBacktest(run);
      setStatus(status, `Backtest #${run.id} finished.`);
    } else {
      setStatus(status, `Backtest #${run.id} failed: ${run.error}`, "error");
    }
  } catch (err) {
    $("#btn-backtest").disabled = false;
    setStatus(status, err.message, "error");
  }
}

async function onBacktest() {
  const status = $("#bt-status");
  $("#btn-backtest").disabled = true;
  setStatus(status, "Starting…");
  try {
    const started = await postJson("/api/backtests", backtestBody());
    $("#bt-progress").hidden = false;
    $("#bt-progress-bar").style.width = "0%";
    await loadBacktests();
    pollBacktest(started.id);
  } catch (err) {
    $("#btn-backtest").disabled = false;
    setStatus(status, `Backtest failed to start: ${err.message}`, "error");
  }
}

async function onBacktestRunClick(event) {
  const tr = event.target.closest("tbody tr");
  if (!tr) return;
  const run = await getJson(`/api/backtests/${tr.dataset.id}`);
  if (run.status === "done") {
    renderBacktest(run);
    setStatus($("#bt-status"), `Loaded backtest #${run.id}.`);
  } else if (run.status === "running") {
    $("#bt-progress").hidden = false;
    pollBacktest(run.id);
  } else {
    setStatus($("#bt-status"), `Backtest #${run.id} ${run.status}: ${run.error ?? ""}`, "error");
  }
}
