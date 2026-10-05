"use strict";
// Statistics section: feature tables.
let analysis = null; // last /api/analysis/features response
let numberSort = { key: "number", dir: 1 };

function numberRows() {
  const w = analysis.features.config.hot_cold_window;
  return analysis.features.numbers.map((n) => ({
    ...n,
    recent_10: n.recent["10"],
    recent_20: n.recent["20"],
    recent_50: n.recent["50"],
    recent_w: n.recent[String(w)],
  }));
}

function renderNumbers() {
  const { key, dir } = numberSort;
  const rows = numberRows().sort((a, b) => {
    const av = a[key] ?? -Infinity;
    const bv = b[key] ?? -Infinity;
    return (av < bv ? -1 : av > bv ? 1 : 0) * dir || a.number - b.number;
  });
  const body = $("#numbers-table tbody");
  body.replaceChildren(
    ...rows.map((n) =>
      el("tr", {}, [
        el("td", {}, pad2(n.number)),
        el("td", {}, n.frequency),
        el("td", {}, fmt(n.frequency_rate, 3)),
        el("td", {}, n.recent_10),
        el("td", {}, n.recent_20),
        el("td", {}, n.recent_50),
        el("td", {}, n.recent_w),
        el("td", {}, n.seen ? n.gap : `${n.gap}+`),
        el("td", {}, fmt(n.average_gap)),
        el("td", {}, fmt(n.gap_deviation)),
        el("td", { title: `observed/expected = ${fmt(n.temperature_ratio)}` }, [
          el("span", { className: `temp temp-${n.temperature}` }, n.temperature),
        ]),
      ]),
    ),
  );
  for (const th of $("#numbers-table").querySelectorAll("th")) {
    th.setAttribute("aria-sort", th.dataset.sort === key ? (dir > 0 ? "ascending" : "descending") : "none");
  }
}

function barCell(observed, expected, scale) {
  return el("td", {}, [
    el("div", { className: "bars", title: `observed ${fmt(observed, 1)}%, expected ${fmt(expected, 1)}%` }, [
      el("span", { className: "bar", style: `width:${(observed / scale) * 100}%` }),
      el("span", { className: "bar expected", style: `width:${(expected / scale) * 100}%` }),
    ]),
  ]);
}

function renderCountDistribution(table, dist, a, b) {
  const k = dist.counts.length - 1;
  const scale = Math.max(...dist.observed_pct, ...dist.expected_pct);
  table.replaceChildren(
    el("thead", {}, el("tr", {}, ["Split", "Draws", "Observed", "Expected", ""].map((h) => el("th", {}, h)))),
    el(
      "tbody",
      {},
      dist.counts.map((c, x) =>
        el("tr", {}, [
          el("td", {}, `${x} ${a} / ${k - x} ${b}`),
          el("td", {}, c),
          el("td", {}, `${fmt(dist.observed_pct[x], 1)}%`),
          el("td", {}, `${fmt(dist.expected_pct[x], 1)}%`),
          barCell(dist.observed_pct[x], dist.expected_pct[x], scale),
        ]),
      ),
    ),
  );
}

function renderSums(s) {
  const rows = [
    ["Min / max", `${s.min} / ${s.max}`],
    ["Mean", `${fmt(s.mean, 1)} (theoretical ${fmt(s.theoretical_mean, 1)})`],
    ["Median", fmt(s.median, 0)],
    ["Std deviation", fmt(s.std, 1)],
    ...Object.entries(s.percentiles).map(([p, v]) => [`P${p}`, fmt(v, 0)]),
  ];
  $("#sum-table").replaceChildren(el("tbody", {}, rows.map(([k, v]) => el("tr", {}, [el("td", {}, k), el("td", {}, v)]))));
}

function renderCombos(block, table, note, combos) {
  block.hidden = !combos;
  if (!combos) return;
  note.textContent = `Expected ${fmt(combos.expected_count)} occurrences each under uniform random draws. ${combos.note}`;
  table.replaceChildren(
    el("thead", {}, el("tr", {}, ["Numbers", "Count", "vs expected"].map((h) => el("th", {}, h)))),
    el(
      "tbody",
      {},
      combos.top.map((c) =>
        el("tr", {}, [
          el("td", {}, c.numbers.map(pad2).join(" – ")),
          el("td", {}, c.count),
          el("td", {}, `×${fmt(c.count / combos.expected_count)}`),
        ]),
      ),
    ),
  );
}

function onSortClick(event) {
  const th = event.target.closest("th[data-sort]");
  if (!th || !analysis) return;
  const key = th.dataset.sort;
  // Numeric columns default to descending (largest first) on first click; Number ascending.
  numberSort = numberSort.key === key ? { key, dir: -numberSort.dir } : { key, dir: key === "number" ? 1 : -1 };
  renderNumbers();
}
