"use strict";
// Combination generation, sessions, CSV export, reproduce check.
let session = null; // currently displayed session

function generationBody(seed) {
  return {
    game: $("#game").value,
    start: $("#from").value || null,
    end: $("#to").value || null,
    window: Number($("#window").value),
    strategy: $("#strategy").value,
    count: Number($("#count").value),
    seed: seed === "" || seed === null || seed === undefined ? null : Number(seed),
    ...scoringOverrides(),
    rules: {
      odd_penalty: $("#rule-odd").checked ? 1 : 0,
      low_penalty: $("#rule-low").checked ? 1 : 0,
      min_spread_fraction: Number($("#rule-spread").value) / 100,
      sum_percentiles: [Number($("#rule-sum-lo").value), Number($("#rule-sum-hi").value)],
      oversample: Number($("#rule-oversample").value),
    },
  };
}

const balls = (numbers) => el("span", { className: "balls" }, numbers.map((n) => el("span", { className: "ball" }, pad2(n))));

function renderSession() {
  const s = session;
  const g = gamesByKey[s.game];
  const strategyLabel = presets[s.strategy] ? $(`#strategy option[value="${s.strategy}"]`).textContent : s.strategy;
  const meta = [
    ["Strategy", strategyLabel],
    ["Seed", s.seed],
    ["Generated", `${s.generated} of ${s.count}`],
    ["History used", `${s.params.n_draws} draws`],
    ["Session", `#${s.id}`],
  ];
  $("#combos-meta").replaceChildren(...meta.map(([k, v]) => el("div", {}, [el("dt", {}, k), el("dd", {}, v)])));
  $("#seed-change").value = s.seed;
  $("#btn-csv").href = `/api/sessions/${s.id}/export.csv`;
  $("#combos-table tbody").replaceChildren(
    ...s.combinations.map((c, i) =>
      el("tr", {}, [
        el("td", {}, i + 1),
        el("td", {}, balls(c.numbers)),
        el("td", {}, fmt(c.number_score)),
        el("td", {}, `${c.pair_score >= 0 ? "+" : ""}${fmt(c.pair_score, 3)}`),
        el("td", {}, fmt(c.distribution_score, 1)),
        el("td", { title: `sum of numbers ${c.total_sum}` }, fmt(c.sum_score, 1)),
        el("td", {}, el("strong", {}, fmt(c.total))),
        el("td", { className: "flag" }, c.flags.join("; ")),
      ]),
    ),
  );
  $("#combos-notes").replaceChildren(
    ...[
      `${g.name}: combination score = sum of number scores (${g.numbers_per_draw}.00 neutral) + pair term − filter penalties.`,
      ...s.notes,
    ].map((n) => el("li", {}, n)),
  );
  for (const tr of $("#sessions-table tbody").children) tr.classList.toggle("selected", Number(tr.dataset.id) === s.id);
  $("#combos-section").hidden = false;
}

async function loadSessions() {
  const list = await getJson(`/api/sessions?game=${encodeURIComponent($("#game").value)}&limit=20`);
  $("#sessions-table tbody").replaceChildren(
    ...list.map((s) => {
      const tr = el("tr", { className: session && session.id === s.id ? "selected" : "" }, [
        el("td", {}, s.id),
        el("td", {}, s.created_at.replace("T", " ").slice(0, 19)),
        el("td", {}, s.strategy),
        el("td", {}, s.seed),
        el("td", {}, s.generated),
        el("td", {}, `${s.start ?? "…"} → ${s.end ?? "…"}`),
        el("td", {}, s.dataset_fingerprint.slice(0, 8)),
      ]);
      tr.dataset.id = s.id;
      return tr;
    }),
  );
  if (list.length && $("#combos-section").hidden) $("#combos-section").hidden = false;
}

async function onGenerate(seed) {
  const buttons = ["#btn-generate", "#btn-again", "#btn-seed"].map((id) => $(id));
  buttons.forEach((b) => (b.disabled = true));
  const status = $("#combos-status");
  setStatus(status, "Generating…");
  $("#combos-section").hidden = false;
  try {
    session = await postJson("/api/generate", generationBody(seed));
    renderSession();
    await loadSessions();
    setStatus(status, `Session #${session.id}: ${session.generated} combinations, seed ${session.seed}.`);
  } catch (err) {
    setStatus(status, `Generation failed: ${err.message}`, "error");
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

async function onReproduce() {
  if (!session) return;
  const status = $("#combos-status");
  setStatus(status, "Regenerating from stored parameters…");
  try {
    const r = await postJson(`/api/sessions/${session.id}/reproduce`, {});
    if (r.matches) setStatus(status, `Reproduced: all ${session.generated} combinations identical (dataset ${r.current_fingerprint}).`);
    else setStatus(status, `Not identical: ${r.differing_rows} row(s) differ. ${r.note ?? ""}`, "warn");
  } catch (err) {
    setStatus(status, `Check failed: ${err.message}`, "error");
  }
}

async function onSessionClick(event) {
  const tr = event.target.closest("tbody tr");
  if (!tr) return;
  try {
    session = await getJson(`/api/sessions/${tr.dataset.id}`);
    renderSession();
    setStatus($("#combos-status"), `Loaded session #${session.id}.`);
  } catch (err) {
    setStatus($("#combos-status"), err.message, "error");
  }
}
