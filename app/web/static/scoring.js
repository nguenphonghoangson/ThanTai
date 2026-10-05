"use strict";
// Phân hệ Điểm số Thuật toán: chỉnh sửa trọng số, bảng xếp hạng điểm, bóc tách thành phần đóng góp.
let presets = {};
let scoring = null; // lưu kết quả /api/analysis/scores gần nhất
let scoreSort = { key: "rank", dir: 1 };
let selectedNumber = null;

const COMPONENT_LABELS = {
  frequency: "Tần suất toàn bộ",
  recent_frequency: "Phong độ kỳ gần",
  gap: "Nhịp vắng mặt (Gan)",
  pair: "Đồng xuất hiện (Cặp số)",
  historical: "Tính ổn định chu kỳ",
};

function describeRaw(name, raw, params) {
  if (raw === null || raw === undefined) return "Không có dữ liệu";
  switch (name) {
    case "frequency":
      return `Tỷ lệ về gấp ×${fmt(raw)} lần kỳ vọng lý thuyết`;
    case "recent_frequency":
      return `Gấp ×${fmt(raw)} lần kỳ vọng trong ${params.feature_config.hot_cold_window} kỳ gần nhất`;
    case "gap":
      return `Vắng mặt gấp ${fmt(raw)}× chu kỳ trung bình (${params.scoring.gap_mode === "overdue" ? "giả thuyết bắt số gan" : "giả thuyết bắt số rơi"})`;
    case "pair":
      return `Độ liên kết đồng xuất hiện ×${fmt(raw)} với các số hàng đầu`;
    case "historical":
      return `Vượt kỳ vọng ở ${Math.round(raw * 100)}% các khối ${params.feature_config.consistency_block} kỳ quay`;
    default:
      return fmt(raw);
  }
}

async function loadStrategies() {
  const list = await getJson("/api/analysis/strategies");
  presets = Object.fromEntries(list.map((p) => [p.key, p]));
}

function applyPreset() {
  const stratEl = $("#strategy");
  if (!stratEl) return;
  const p = presets[stratEl.value];
  if (!p) return;
  for (const input of document.querySelectorAll("[data-weight]")) {
    input.value = p.weights[input.dataset.weight];
  }
  const intInput = $("#intensity");
  if (intInput) intInput.value = p.intensity;
  const gapInput = $("#gap-mode");
  if (gapInput) gapInput.value = p.gap_mode;
  const weightsEl = $("#weights");
  if (weightsEl) weightsEl.disabled = p.uniform;
}

function scoringOverrides() {
  const stratEl = $("#strategy");
  if (!stratEl) return { weights: {} };
  const p = presets[stratEl.value];
  const out = { weights: {} };
  if (!p || p.uniform) return out;
  for (const input of document.querySelectorAll("[data-weight]")) {
    const v = Number(input.value);
    if (v !== p.weights[input.dataset.weight]) out.weights[input.dataset.weight] = v;
  }
  const intVal = Number($("#intensity").value);
  if (intVal !== p.intensity) out.intensity = intVal;
  const gapVal = $("#gap-mode").value;
  if (gapVal !== p.gap_mode) out.gap_mode = gapVal;
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
  const tbody = $("#scores-table tbody");
  if (!tbody) return;
  tbody.replaceChildren(
    ...rows.map((s) => {
      const ballColorIndex = Math.min(5, Math.floor(s.number / 10));
      const tr = el("tr", { className: s.number === selectedNumber ? "selected" : "" }, [
        el("td", { className: "col-num-cell" }, [
          el("span", { className: `ball mini-ball ball-${ballColorIndex}` }, pad2(s.number)),
        ]),
        el("td", {}, s.frequency),
        el("td", {}, s.recent),
        el("td", { className: s.gap >= 15 ? "cell-warning" : "" }, s.seen ? s.gap : `${s.gap}+`),
        el("td", { className: "cell-highlight cell-bold" }, fmt(s.score, 3)),
        el("td", { className: "cell-rank" }, `#${s.rank}`),
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
  if (!box || !scoring) return;
  const s = scoring.scores.find((x) => x.number === selectedNumber);
  if (!s) {
    box.replaceChildren(el("p", { className: "muted" }, "Chọn một số bất kỳ trong bảng để xem chi tiết lý do và thành phần điểm số."));
    return;
  }
  const signed = (v) => el("span", { className: v > 0 ? "pos" : v < 0 ? "neg" : "" }, `${v >= 0 ? "+" : ""}${fmt(v, 3)}`);
  const rows = s.components.map((c) =>
    el("tr", { title: `z-score = ${fmt(c.z)}, trọng số = ${fmt(c.weight)}` }, [
      el("td", {}, [
        el("div", { className: "cell-bold" }, COMPONENT_LABELS[c.name] || c.name),
        el("div", { className: "muted text-xs" }, describeRaw(c.name, c.raw, scoring.params)),
      ]),
      el("td", { className: "cell-contrib" }, signed(c.contribution)),
    ]),
  );
  const total = s.components.reduce((a, c) => a + c.contribution, 0);
  const floored = Math.abs(1 + total - s.score) > 1e-9;
  const ballColorIndex = Math.min(5, Math.floor(s.number / 10));

  box.replaceChildren(
    el("div", { className: "breakdown-header" }, [
      el("span", { className: `ball ball-${ballColorIndex}` }, pad2(s.number)),
      el("div", {}, [
        el("h3", {}, `Bóng số ${pad2(s.number)}`),
        el("span", { className: "badge badge-primary" }, `Xếp hạng #${s.rank}`),
      ]),
    ]),
    el("table", { className: "data modern-table breakdown-table" }, [
      el("tbody", {}, [
        el("tr", {}, [el("td", {}, "Mức chuẩn trung hòa (Neutral)"), el("td", {}, "1.000")]),
        ...rows,
        el("tr", { className: "total-row" }, [
          el("td", { className: "cell-bold" }, floored ? "Điểm tổng hợp (đã chặn sàn 0.05)" : "Điểm tổng hợp cuối"),
          el("td", { className: "cell-bold cell-highlight" }, fmt(s.score, 3)),
        ]),
      ]),
    ]),
    el("p", { className: "muted breakdown-footnote" },
      s.components.length
        ? "Mức đóng góp = Cường độ × Trọng số × z-score (độ lệch chuẩn so với giá trị trung bình toàn bộ dải số)."
        : "Chiến lược ngẫu nhiên đối chứng: mọi số đều có điểm số 1.000 như nhau."),
  );
}

function renderScoring() {
  const g = gamesByKey[scoring.params.game];
  const stratSelect = $("#strategy");
  const label = (stratSelect?.selectedOptions[0]?.textContent || scoring.strategy) + (scoring.customized ? " (Tùy biến)" : "");
  const scopeEl = $("#scores-scope");
  if (scopeEl) {
    scopeEl.textContent = `${g.name} · ${label} · ${scoring.params.n_draws} kỳ quay`;
  }
  const rwHead = $("#scores-recent-head");
  if (rwHead) {
    rwHead.textContent = `Về ${scoring.params.feature_config.hot_cold_window} kỳ`;
  }
  const notesEl = $("#scores-notes");
  if (notesEl) {
    notesEl.replaceChildren(...scoring.notes.map((n) => el("li", {}, n)));
  }
  const paramsEl = $("#scores-params");
  if (paramsEl) {
    paramsEl.textContent = JSON.stringify(scoring.params, null, 2);
  }
  if (selectedNumber === null) {
    const topScorer = scoring.scores.find((s) => s.rank === 1);
    selectedNumber = topScorer ? topScorer.number : scoring.scores[0].number;
  }
  renderScoreChart();
  renderScores();
  renderBreakdown();
  const scoresSection = $("#scores-section");
  if (scoresSection) scoresSection.hidden = false;
}

async function runScoring() {
  const params = scoringParams();
  for (const k of ["game", "from", "to", "window"]) {
    const elInput = $(`#${k}`);
    if (elInput) params.set(k, elInput.value);
  }
  scoring = await getJson(`/api/analysis/scores?${params}`);
  renderScoring();
}

async function onRescore() {
  if (!scoring) return;
  try {
    await runScoring();
  } catch (err) {
    setStatus($("#fetch-status"), `Lỗi tính điểm thuật toán: ${err.message}`, "error");
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
  if (tr && tr.dataset.number) {
    selectedNumber = Number(tr.dataset.number);
    renderScores();
    renderBreakdown();
  }
}
