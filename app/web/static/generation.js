"use strict";
// Phân hệ Sinh tổ hợp số: tạo vé dự thưởng, quản lý phiên, xuất CSV và xác minh tính tái lập.
let session = null; // phiên đang hiển thị hiện tại

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

const balls = (numbers) =>
  el(
    "span",
    { className: "balls" },
    numbers.map((n) =>
      el("span", { className: `ball ball-${Math.min(5, Math.floor(n / 10))}` }, pad2(n))
    )
  );

function renderSession() {
  const s = session;
  const g = gamesByKey[s.game];
  const strategyOpt = $(`#strategy option[value="${s.strategy}"]`);
  const strategyLabel = strategyOpt ? strategyOpt.textContent : s.strategy;
  const meta = [
    ["Chiến lược áp dụng", strategyLabel],
    ["Hạt giống (Seed)", s.seed],
    ["Số lượng bộ số", `${s.generated} / ${s.count} bộ`],
    ["Kỳ quay lịch sử", `${s.params.n_draws} kỳ`],
    ["Mã phiên (Session)", `#${s.id}`],
  ];
  const metaBox = $("#combos-meta");
  if (metaBox) {
    metaBox.replaceChildren(...meta.map(([k, v]) =>
      el("div", { className: "stat-card" }, [
        el("dt", {}, k),
        el("dd", {}, v),
        el("span", { className: "stat-sub" }, "Tham số phiên")
      ])
    ));
  }
  const seedChange = $("#seed-change");
  if (seedChange) seedChange.value = s.seed;
  const btnCsv = $("#btn-csv");
  if (btnCsv) btnCsv.href = `/api/sessions/${s.id}/export.csv`;
  
  const tbody = $("#combos-table tbody");
  if (tbody) {
    tbody.replaceChildren(
      ...s.combinations.map((c, i) =>
        el("tr", {}, [
          el("td", { className: "col-stt-cell cell-bold" }, i + 1),
          el("td", { className: "col-combo-cell" }, balls(c.numbers)),
          el("td", {}, fmt(c.number_score)),
          el("td", {}, `${c.pair_score >= 0 ? "+" : ""}${fmt(c.pair_score, 3)}`),
          el("td", { className: c.distribution_score < 0 ? "cell-penalty" : "" }, fmt(c.distribution_score, 1)),
          el("td", { className: c.sum_score < 0 ? "cell-penalty" : "", title: `Tổng điểm 6 số = ${c.total_sum}` }, fmt(c.sum_score, 1)),
          el("td", { className: "cell-highlight cell-bold" }, el("strong", {}, fmt(c.total))),
          el("td", { className: c.flags.length ? "col-flags-cell flag" : "col-flags-cell" }, c.flags.length ? c.flags.join("; ") : "—"),
        ]),
      ),
    );
  }
  const notesBox = $("#combos-notes");
  if (notesBox) {
    notesBox.replaceChildren(
      ...[
        `${g.name}: Điểm tổ hợp = Tổng điểm các số (${g.numbers_per_draw}.00 mức chuẩn) + Điểm cặp đồng quy − Điểm phạt bộ lọc quy luật.`,
        ...s.notes,
      ].map((n) => el("li", {}, n)),
    );
  }
  const sessionsTable = $("#sessions-table tbody");
  if (sessionsTable) {
    for (const tr of sessionsTable.children) {
      tr.classList.toggle("selected", Number(tr.dataset.id) === s.id);
    }
  }
  const combosSection = $("#combos-section");
  if (combosSection) combosSection.hidden = false;
}

async function loadSessions() {
  const gameVal = $("#game") ? $("#game").value : "mega645";
  const list = await getJson(`/api/sessions?game=${encodeURIComponent(gameVal)}&limit=20`);
  const tbody = $("#sessions-table tbody");
  if (!tbody) return;
  tbody.replaceChildren(
    ...list.map((s) => {
      const tr = el("tr", { className: session && session.id === s.id ? "selected" : "" }, [
        el("td", { className: "cell-bold" }, `#${s.id}`),
        el("td", {}, s.created_at.replace("T", " ").slice(0, 19)),
        el("td", {}, s.strategy),
        el("td", {}, s.seed),
        el("td", {}, `${s.generated} bộ`),
        el("td", {}, `${s.start ?? "…"} → ${s.end ?? "…"}`),
        el("td", { className: "text-mono" }, s.dataset_fingerprint.slice(0, 8)),
      ]);
      tr.dataset.id = s.id;
      return tr;
    }),
  );
  if (list.length && $("#combos-section") && $("#combos-section").hidden) {
    $("#combos-section").hidden = false;
  }
}

async function onGenerate(seed) {
  const buttons = ["#btn-generate", "#btn-again", "#btn-seed"].map((id) => $(id)).filter(Boolean);
  buttons.forEach((b) => (b.disabled = true));
  const status = $("#combos-status");
  setStatus(status, "Đang tính toán và sinh bộ số dự thưởng tối ưu…");
  const combosSection = $("#combos-section");
  if (combosSection) combosSection.hidden = false;
  try {
    session = await postJson("/api/generate", generationBody(seed));
    renderSession();
    await loadSessions();
    setStatus(status, `Phiên #${session.id}: Đã sinh thành công ${session.generated} bộ số, hạt giống: ${session.seed}.`, "success");
    
    // Đảm bảo cuộn nhẹ đến kết quả
    combosSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    setStatus(status, `Lỗi sinh số: ${err.message}`, "error");
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

async function onReproduce() {
  if (!session) return;
  const status = $("#combos-status");
  setStatus(status, "Đang tính toán tái lập từ các tham số đã lưu trữ…");
  try {
    const r = await postJson(`/api/sessions/${session.id}/reproduce`, {});
    if (r.matches) {
      setStatus(status, `Xác nhận tái lập hoàn hảo: Toàn bộ ${session.generated} bộ số trùng khớp tuyệt đối 100% (Bản vân dữ liệu: ${r.current_fingerprint}).`, "success");
    } else {
      setStatus(status, `Cảnh báo không trùng khớp: Phát hiện ${r.differing_rows} bộ số khác biệt. ${r.note ?? ""}`, "warn");
    }
  } catch (err) {
    setStatus(status, `Lỗi kiểm tra tái lập: ${err.message}`, "error");
  }
}

async function onSessionClick(event) {
  const tr = event.target.closest("tbody tr");
  if (!tr) return;
  try {
    session = await getJson(`/api/sessions/${tr.dataset.id}`);
    renderSession();
    setStatus($("#combos-status"), `Đã tải dữ liệu phiên sinh số #${session.id}.`, "success");
  } catch (err) {
    setStatus($("#combos-status"), `Lỗi nạp phiên: ${err.message}`, "error");
  }
}
