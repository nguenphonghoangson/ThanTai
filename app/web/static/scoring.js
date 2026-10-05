"use strict";
// Number scores: weight editor, score table, breakdown.
let presets = {};
let scoring = null; // last /api/analysis/scores response
let scoreSort = { key: "rank", dir: 1 };
let selectedNumber = null;

const COMPONENT_LABELS = {
  frequency: "Frequency",
  recent_frequency: "Recent",
  gap: "Gap",
  pair: "Pair",
  historical: "Historical",
};

function describeRaw(name, raw, params) {
  if (raw === null || raw === undefined) return "n/a";
  switch (name) {
    case "frequency":
      return `rate ×${fmt(raw)} of expected`;
    case "recent_frequency":
      return `×${fmt(raw)} expected in last ${params.feature_config.hot_cold_window}`;
    case "gap":
      return `gap ${fmt(raw)}× its average${raw > 3 ? ", capped at 3" : ""} (${params.scoring.gap_mode} hypothesis)`;
    case "pair":
      return `×${fmt(raw)} co-occurrence with top numbers`;
    case "historical":
      return `above expected in ${Math.round(raw * 100)}% of ${params.feature_config.consistency_block}-draw blocks`;
    default:
      return fmt(raw);
  }
}

async function loadStrategies() {
  const list = await getJson("/api/analysis/strategies");
  presets = Object.fromEntries(list.map((p) => [p.key, p]));
}

function applyPreset() {
  const p = presets[$("#strategy").value];
  if (!p) return;
  for (const input of document.querySelectorAll("[data-weight]")) input.value = p.weights[input.dataset.weight];
  $("#intensity").value = p.intensity;
  $("#gap-mode").value = p.gap_mode;
  $("#weights").disabled = p.uniform;
}

function scoringOverrides() {
  const p = presets[$("#strategy").value];
  const out = { weights: {} };
  if (!p || p.uniform) return out;
  for (const input of document.querySelectorAll("[data-weight]")) {
    const v = Number(input.value);
    if (v !== p.weights[input.dataset.weight]) out.weights[input.dataset.weight] = v;
  }
  if (Number($("#intensity").value) !== p.intensity) out.intensity = Number($("#intensity").value);
  if ($("#gap-mode").value !== p.gap_mode) out.gap_mode = $("#gap-mode").value;
  return out;
}

function scoringParams() {
  const params = new URLSearchParams({ strategy: $("#strategy").value });
  const o = scoringOverrides();
  const keyMap = { frequency: "w_frequency", recent_frequency: "w_recent", gap: "w_gap", pair: "w_pair", historical: "w_historical" };
  for (const [k, v] of Object.entries(o.weights)) params.set(keyMap[k], v);
  if (o.intensity !== undefined) params.set("intensity", o.intensity);
  if (o.gap_mode !== undefined) params.set("gap_mode", o.gap_mode);
  return params;
}

function renderScores() {
  const { key, dir } = scoreSort;
  const rows = [...scoring.scores].sort((a, b) => (a[key] < b[key] ? -1 : a[key] > b[key] ? 1 : 0) * dir || a.number - b.number);
  $("#scores-table tbody").replaceChildren(
    ...rows.map((s) => {
      const tr = el("tr", { className: s.number === selectedNumber ? "selected" : "" }, [
        el("td", {}, pad2(s.number)),
        el("td", {}, s.frequency),
        el("td", {}, s.recent),
        el("td", {}, s.seen ? s.gap : `${s.gap}+`),
        el("td", {}, fmt(s.score, 3)),
        el("td", {}, s.rank),
      ]);
      tr.dataset.number = s.number;
      return tr;
    }),
  );
  for (const th of $("#scores-table").querySelectorAll("th")) {
    th.setAttribute("aria-sort", th.dataset.sort === key ? (dir > 0 ? "ascending" : "descending") : "none");
  }
}

function renderBreakdown() {
  const box = $("#breakdown");
  const s = scoring.scores.find((x) => x.number === selectedNumber);
  if (!s) {
    box.replaceChildren(el("p", { className: "muted" }, "Select a number to see why it scores the way it does."));
    return;
  }
  const signed = (v) => el("span", { className: v > 0 ? "pos" : v < 0 ? "neg" : "" }, `${v >= 0 ? "+" : ""}${fmt(v, 3)}`);
  const rows = s.components.map((c) =>
    el("tr", { title: `z = ${fmt(c.z)}, weight ${fmt(c.weight)}` }, [
      el("td", {}, [el("div", {}, COMPONENT_LABELS[c.name]), el("div", { className: "muted" }, describeRaw(c.name, c.raw, scoring.params))]),
      el("td", {}, signed(c.contribution)),
    ]),
  );
  const total = s.components.reduce((a, c) => a + c.contribution, 0);
  const floored = Math.abs(1 + total - s.score) > 1e-9;
  box.replaceChildren(
    el("h3", {}, `Number ${pad2(s.number)} · rank ${s.rank}`),
    el("table", { className: "data" }, [
      el("tbody", {}, [
        el("tr", {}, [el("td", {}, "Neutral baseline"), el("td", {}, "1.000")]),
        ...rows,
        el("tr", { className: "total" }, [el("td", {}, floored ? "Final score (floored)" : "Final score"), el("td", {}, fmt(s.score, 3))]),
      ]),
    ]),
    el("p", { className: "muted" },
      s.components.length
        ? "Contribution = intensity × weight × z, where z is how far the number sits from the pool average on that component."
        : "Random baseline: every number has the same score."),
  );
}

function renderScoring() {
  const g = gamesByKey[scoring.params.game];
  const label = $("#strategy").selectedOptions[0].textContent + (scoring.customized ? " (custom)" : "");
  $("#scores-scope").textContent = `${g.name} · ${label} · ${scoring.params.n_draws} draws`;
  $("#scores-recent-head").textContent = `R${scoring.params.feature_config.hot_cold_window}`;
  $("#scores-notes").replaceChildren(...scoring.notes.map((n) => el("li", {}, n)));
  $("#scores-params").textContent = JSON.stringify(scoring.params, null, 2);
  if (selectedNumber === null) selectedNumber = scoring.scores.find((s) => s.rank === 1).number;
  renderScoreChart();
  renderScores();
  renderBreakdown();
  $("#scores-section").hidden = false;
}

async function runScoring() {
  const params = scoringParams();
  for (const k of ["game", "from", "to", "window"]) params.set(k, $(`#${k}`).value);
  scoring = await getJson(`/api/analysis/scores?${params}`);
  renderScoring();
}

async function onRescore() {
  if (!scoring) return;
  try {
    await runScoring();
  } catch (err) {
    setStatus($("#fetch-status"), `Scoring failed: ${err.message}`, "error");
  }
}

function onScoresTableClick(event) {
  const th = event.target.closest("th[data-sort]");
  if (th) {
    const key = th.dataset.sort;
    const ascFirst = key === "number" || key === "rank";
    scoreSort = scoreSort.key === key ? { key, dir: -scoreSort.dir } : { key, dir: ascFirst ? 1 : -1 };
    renderScores();
    return;
  }
  const tr = event.target.closest("tbody tr");
  if (tr) {
    selectedNumber = Number(tr.dataset.number);
    renderScores();
    renderBreakdown();
  }
}
