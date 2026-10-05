"use strict";
// Phân hệ Thống kê: kết xuất các bảng ma trận đặc trưng (Features).
let analysis = null; // lưu trữ phản hồi /api/analysis/features gần nhất
let numberSort = { key: "number", dir: 1 };

const TEMP_LABELS = {
  HOT: "Cực nóng 🔥",
  WARM: "Ấm ⚡",
  COLD: "Lô gan ❄️",
  NORMAL: "Bình thường ⚪",
};

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
  if (!body) return;
  body.replaceChildren(
    ...rows.map((n) => {
      const ballColorIndex = Math.min(5, Math.floor(n.number / 10));
      return el("tr", {}, [
        el("td", { className: "col-num-cell" }, [
          el("span", { className: `ball mini-ball ball-${ballColorIndex}` }, pad2(n.number)),
        ]),
        el("td", { className: "cell-bold" }, n.frequency),
        el("td", {}, `${(n.frequency_rate * 100).toFixed(1)}%`),
        el("td", {}, n.recent_10),
        el("td", {}, n.recent_20),
        el("td", {}, n.recent_50),
        el("td", { className: "cell-highlight" }, n.recent_w),
        el("td", { className: n.gap >= 15 ? "cell-warning" : "" }, n.seen ? n.gap : `${n.gap}+`),
        el("td", {}, fmt(n.average_gap)),
        el("td", {}, fmt(n.gap_deviation)),
        el("td", { title: `Tỷ lệ thực tế / Kỳ vọng lý thuyết = ${fmt(n.temperature_ratio)}` }, [
          el("span", { className: `temp temp-${n.temperature}` }, TEMP_LABELS[n.temperature] || n.temperature),
        ]),
      ]);
    }),
  );
  for (const th of $("#numbers-table").querySelectorAll("th")) {
    th.setAttribute("aria-sort", th.dataset.sort === key ? (dir > 0 ? "ascending" : "descending") : "none");
  }
}

function barCell(observed, expected, scale) {
  return el("td", {}, [
    el("div", { className: "bars", title: `Thực tế: ${fmt(observed, 1)}%, Lý thuyết: ${fmt(expected, 1)}%` }, [
      el("span", { className: "bar", style: `width:${(observed / scale) * 100}%` }),
      el("span", { className: "bar expected", style: `width:${(expected / scale) * 100}%` }),
    ]),
  ]);
}

function renderCountDistribution(table, dist, a, b) {
  if (!table) return;
  const k = dist.counts.length - 1;
  const scale = Math.max(...dist.observed_pct, ...dist.expected_pct);
  table.replaceChildren(
    el("thead", {}, el("tr", {}, ["Phân chia", "Số kỳ về", "Tỷ lệ thực tế", "Kỳ vọng lý thuyết", "Trực quan"].map((h) => el("th", {}, h)))),
    el(
      "tbody",
      {},
      dist.counts.map((c, x) =>
        el("tr", {}, [
          el("td", { className: "cell-bold" }, `${x} ${a} / ${k - x} ${b}`),
          el("td", {}, c),
          el("td", { className: "cell-highlight" }, `${fmt(dist.observed_pct[x], 1)}%`),
          el("td", { className: "text-muted" }, `${fmt(dist.expected_pct[x], 1)}%`),
          barCell(dist.observed_pct[x], dist.expected_pct[x], scale),
        ]),
      ),
    ),
  );
}

function renderSums(s) {
  const rows = [
    ["Nhỏ nhất / Lớn nhất", `${s.min} / ${s.max}`],
    ["Tổng điểm trung bình", `${fmt(s.mean, 1)} (Lý thuyết: ${fmt(s.theoretical_mean, 1)})`],
    ["Trung vị (Median)", fmt(s.median, 0)],
    ["Độ lệch chuẩn (Std Dev)", fmt(s.std, 1)],
    ...Object.entries(s.percentiles).map(([p, v]) => [`Bách phân vị P${p}`, fmt(v, 0)]),
  ];
  const sumTable = $("#sum-table");
  if (sumTable) {
    sumTable.replaceChildren(el("tbody", {}, rows.map(([k, v]) => el("tr", {}, [el("td", { className: "cell-bold" }, k), el("td", {}, v)]))));
  }
}

function renderCombos(block, table, note, combos) {
  if (!block) return;
  block.hidden = !combos;
  if (!combos || !table) return;
  if (note) {
    note.textContent = `Kỳ vọng lý thuyết mỗi tổ hợp xuất hiện khoảng ${fmt(combos.expected_count)} lần theo phân bố đều ngẫu nhiên. ${combos.note}`;
  }
  table.replaceChildren(
    el("thead", {}, el("tr", {}, ["Bộ số", "Số lần cùng về", "Tỷ lệ so với kỳ vọng"].map((h) => el("th", {}, h)))),
    el(
      "tbody",
      {},
      combos.top.map((c) =>
        el("tr", {}, [
          el("td", { className: "col-combo-tokens" }, [
            el("span", { className: "balls mini-balls" }, c.numbers.map((n) =>
              el("span", { className: `ball mini-ball ball-${Math.min(5, Math.floor(n / 10))}` }, pad2(n))
            ))
          ]),
          el("td", { className: "cell-bold" }, `${c.count} kỳ`),
          el("td", { className: "cell-highlight" }, `×${fmt(c.count / combos.expected_count)} lần`),
        ]),
      ),
    ),
  );
}

function onSortClick(event) {
  const th = event.target.closest("th[data-sort]");
  if (!th || !analysis) return;
  const key = th.dataset.sort;
  // Cột số sắp xếp tăng dần mặc định; các cột chỉ số sắp xếp giảm dần trước
  numberSort = numberSort.key === key ? { key, dir: -numberSort.dir } : { key, dir: key === "number" ? 1 : -1 };
  renderNumbers();
}
