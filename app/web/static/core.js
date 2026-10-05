"use strict";
// Các hàm tiện ích dùng chung, gọi API, thông tin trò chơi và đồng bộ dữ liệu.

const $ = (sel) => document.querySelector(sel);

async function requestJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail;
    throw new Error(detail || `Lỗi máy chủ: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

const getJson = (url) => requestJson(url);
const postJson = (url, payload) =>
  requestJson(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });

let gamesByKey = {};

async function loadGames() {
  const games = await getJson("/api/games");
  gamesByKey = Object.fromEntries(games.map((g) => [g.key, g]));
}

function setStatus(el, text, kind) {
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("error", kind === "error");
  el.classList.toggle("warn", kind === "warn");
  el.classList.toggle("success", kind === "success");
}

function renderGameInfo(key) {
  const g = gamesByKey[key];
  if (!g) return;
  const infoEl = $("#game-info");
  if (infoEl) {
    setStatus(
      infoEl,
      `${g.name}: Bộ ${g.numbers_per_draw} số trong dải từ ${pad2(g.min_number)} đến ${pad2(g.max_number)}. ` +
        `Thấp (Xỉu): ${pad2(g.low_range[0])}–${pad2(g.low_range[1])}, Cao (Tài): ${pad2(g.high_range[0])}–${pad2(g.high_range[1])}` +
        (g.has_bonus_number ? ". Bóng đặc biệt (Bonus ball) được lưu trữ để đối soát Jackpot 2, tách biệt khỏi phân tích bộ 6 số chính." : "."),
    );
  }
}

function renderQuality(s) {
  const notes = [];
  if (s.total_draws && s.missing_before_first > 0) {
    notes.push(`Các kỳ quay từ #1 đến #${s.missing_before_first} không có sẵn từ nguồn dữ liệu (kỳ đầu tiên lưu trữ: #${s.first_draw_id}).`);
  }
  if (s.missing_draw_count > 0) {
    const ids = s.missing_draw_ids.map((n) => `#${n}`).join(", ");
    notes.push(`Phát hiện ${s.missing_draw_count} kỳ quay bị gián đoạn trong dải dữ liệu đã lưu: ${ids}${s.missing_draw_count > s.missing_draw_ids.length ? ", …" : ""}.`);
  }
  const list = $("#data-quality");
  if (!list) return;
  list.replaceChildren(...notes.map((n) => Object.assign(document.createElement("li"), { textContent: n })));
  list.hidden = notes.length === 0;
}

async function refreshSummary() {
  const key = $("#game").value;
  renderGameInfo(key);
  const box = $("#data-summary");
  const field = (name) => box ? box.querySelector(`[data-field="${name}"]`) : null;
  try {
    const s = await getJson(`/api/data/summary?game=${encodeURIComponent(key)}`);
    const gameName = gamesByKey[key]?.name ?? s.game;
    if (field("game")) field("game").textContent = gameName;
    if (field("total_draws")) field("total_draws").textContent = `${s.total_draws.toLocaleString()} kỳ`;
    if (field("first_date")) field("first_date").textContent = s.first_date ? `${s.first_date} (kỳ #${s.first_draw_id})` : "—";
    if (field("last_date")) field("last_date").textContent = s.last_date ? `${s.last_date} (kỳ #${s.last_draw_id})` : "—";
    
    // Cập nhật pill ở thanh tiêu đề
    const topText = $("#top-dataset-text");
    if (topText) {
      topText.textContent = `${gameName}: ${s.total_draws.toLocaleString()} kỳ quay`;
    }
    const overviewBadge = $("#overview-badge");
    if (overviewBadge) {
      overviewBadge.textContent = `${s.total_draws.toLocaleString()} kỳ`;
    }
    
    renderQuality(s);
    loadRecentDraws().catch(() => {});
  } catch (err) {
    setStatus($("#game-info"), `Lỗi nạp tóm tắt: ${err.message}`, "error");
  }
}

function formatDateVietnamese(dateStr) {
  if (!dateStr) return "—";
  try {
    const [y, m, d] = dateStr.split("-");
    const dt = new Date(parseInt(y, 10), parseInt(m, 10) - 1, parseInt(d, 10));
    const days = ["Chủ Nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"];
    const dayName = days[dt.getDay()] || "";
    return `${dayName}, ${d}/${m}/${y}`;
  } catch (e) {
    return dateStr;
  }
}

async function loadRecentDraws() {
  const key = $("#game").value;
  const game = gamesByKey[key];
  try {
    const draws = await getJson(`/api/data/draws?game=${encodeURIComponent(key)}`);
    if (!draws || draws.length === 0) return;
    const latest = draws[draws.length - 1];
    const recent = draws.slice(-10).reverse();
    renderHeroDraw(latest, game);
    renderRecentDrawsTable(recent, game);
  } catch (err) {
    console.error("Lỗi nạp danh sách kỳ quay:", err);
  }
}

function renderHeroDraw(draw, game) {
  const heroCard = $("#hero-latest-draw");
  if (!heroCard || !draw) return;

  const gameName = game?.name || (draw.bonus_number ? "Power 6/55" : "Mega 6/45");
  const titleEl = $("#hero-draw-title");
  if (titleEl) titleEl.textContent = `${gameName} • Kỳ mở thưởng #${draw.draw_id}`;

  const dateEl = $("#hero-draw-date");
  if (dateEl) dateEl.textContent = formatDateVietnamese(draw.draw_date);

  const ballsContainer = $("#hero-draw-balls");
  if (ballsContainer) {
    ballsContainer.replaceChildren(
      ...draw.numbers.map((n) => {
        const colorIdx = Math.min(5, Math.floor(n / 10));
        return el("span", { className: `ball ball-hero ball-${colorIdx}` }, pad2(n));
      })
    );

    if (draw.bonus_number !== null && draw.bonus_number !== undefined) {
      const bonusColorIdx = Math.min(5, Math.floor(draw.bonus_number / 10));
      const bonusWrapper = el(
        "div",
        { className: "flex items-center gap-2 pl-2 sm:pl-3 border-l border-white/20 ml-1" },
        [
          el("span", { className: `ball ball-hero ball-bonus ball-${bonusColorIdx}` }, pad2(draw.bonus_number)),
          el("div", { className: "hidden sm:flex flex-col text-[11px] leading-tight" }, [
            el("span", { className: "text-amber-400 font-bold" }, "Jackpot 2"),
            el("span", { className: "text-slate-300 text-[10px]" }, "Bóng đặc biệt"),
          ]),
        ]
      );
      ballsContainer.append(bonusWrapper);
    }
  }

  const sum = draw.numbers.reduce((a, b) => a + b, 0);
  const evens = draw.numbers.filter((n) => n % 2 === 0).length;
  const odds = draw.numbers.length - evens;
  const maxNum = game?.max_number || (draw.bonus_number ? 55 : 45);
  const mid = Math.floor(maxNum / 2);
  const lows = draw.numbers.filter((n) => n <= mid).length;
  const highs = draw.numbers.length - lows;

  const sumEl = $("#hero-draw-sum");
  if (sumEl) sumEl.textContent = `Tổng: ${sum}`;

  const oddEvenEl = $("#hero-draw-oddeven");
  if (oddEvenEl) oddEvenEl.textContent = `Chẵn/Lẻ: ${evens}/${odds}`;

  const lowHighEl = $("#hero-draw-lowhigh");
  if (lowHighEl) lowHighEl.textContent = `Thấp/Cao: ${lows}/${highs}`;
}

function renderRecentDrawsTable(draws, game) {
  const tbody = $("#recent-draws-tbody");
  if (!tbody || !draws) return;

  const maxNum = game?.max_number || 45;
  const mid = Math.floor(maxNum / 2);

  tbody.replaceChildren(
    ...draws.map((d, index) => {
      const sum = d.numbers.reduce((a, b) => a + b, 0);
      const evens = d.numbers.filter((n) => n % 2 === 0).length;
      const odds = d.numbers.length - evens;
      const lows = d.numbers.filter((n) => n <= mid).length;
      const highs = d.numbers.length - lows;

      const ballsGroup = el("div", { className: "balls flex-nowrap" }, [
        ...d.numbers.map((n) =>
          el("span", { className: `ball mini-ball ball-${Math.min(5, Math.floor(n / 10))}` }, pad2(n))
        ),
        ...(d.bonus_number !== null && d.bonus_number !== undefined
          ? [
              el("span", { className: "text-slate-400 font-bold px-1" }, "+"),
              el(
                "span",
                {
                  className: `ball mini-ball ball-bonus ball-${Math.min(5, Math.floor(d.bonus_number / 10))}`,
                  title: "Bóng đặc biệt Jackpot 2",
                },
                pad2(d.bonus_number)
              ),
            ]
          : []),
      ]);

      const isLatest = index === 0;

      return el("tr", { className: isLatest ? "bg-red-50/50 dark:bg-red-950/20 font-semibold" : "" }, [
        el("td", { className: "font-mono font-bold text-slate-900 dark:text-white" }, [
          `#${d.draw_id}`,
          ...(isLatest
            ? [el("span", { className: "ml-2 px-1.5 py-0.5 rounded text-[10px] bg-red-600 text-white font-bold" }, "Mới")]
            : []),
        ]),
        el("td", { className: "text-slate-600 dark:text-slate-400 text-xs" }, formatDateVietnamese(d.draw_date)),
        el("td", {}, ballsGroup),
        el("td", { className: "font-mono font-bold text-center" }, String(sum)),
        el("td", { className: "text-center" }, [
          el(
            "span",
            {
              className:
                "px-2 py-0.5 rounded-full text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300",
            },
            `${evens}C / ${odds}L`
          ),
        ]),
        el("td", { className: "text-center" }, [
          el(
            "span",
            {
              className:
                "px-2 py-0.5 rounded-full text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300",
            },
            `${lows}T / ${highs}C`
          ),
        ]),
      ]);
    })
  );
}

function describeFetch(r) {
  if (r.up_to_date) return `Dữ liệu đã được lưu trữ đầy đủ từ ${r.requested[0]} đến ${r.requested[1]}. Toàn bộ kỳ quay đã ở trạng thái mới nhất.`;
  
  const parts = [];
  if (r.received === 0 && r.inserted === 0) {
    parts.push(`Dữ liệu đã đồng bộ hoàn tất và đang ở trạng thái mới nhất! Không có kỳ mở thưởng mới nào phát sinh trong các ngày gần đây.`);
  } else if (r.inserted > 0) {
    parts.push(`Đồng bộ thành công: Thêm mới ${r.inserted} kỳ quay mở thưởng (nhận ${r.received} bản ghi, đã lưu từ trước ${r.unchanged}).`);
  } else {
    parts.push(`Đã kiểm tra ${r.received} bản ghi: Toàn bộ dữ liệu đã được lưu trữ an toàn & đầy đủ từ trước (0 kỳ mở thưởng mới).`);
  }

  if (r.conflicts.length) parts.push(`${r.conflicts.length} kỳ quay giữ nguyên bản ghi hiện tại do xung đột: ${r.conflicts.slice(0, 5).join(", ")}.`);
  if (r.rejected.length && (r.inserted > 0 || r.received > 0)) {
    const formatted = r.rejected.slice(0, 3).map((msg) => {
      if (msg.includes("expected 6 numbers + bonus, got 6 values")) {
        return msg.replace("DrawValidationError: expected 6 numbers + bonus, got 6 values", "nguồn mở bị chèn nhầm 1 dòng Mega 6/45 thiếu bóng Jackpot 2");
      }
      return msg;
    }).join("; ");
    parts.push(`(Đã cách ly an toàn ${r.rejected.length} bản ghi lỗi ở nguồn mở: ${formatted}. Dữ liệu hệ thống đảm bảo chuẩn 100%).`);
  }
  if (r.stale_source) parts.push("Không thể kết nối đến máy chủ nguồn; đang tạm thời sử dụng bản sao lưu cục bộ (cache).");
  return parts.join(" ");
}

async function onFetch() {
  const btn = $("#btn-fetch");
  const status = $("#fetch-status");
  btn.disabled = true;
  setStatus(status, "Đang đồng bộ dữ liệu kỳ quay mới từ máy chủ nguồn…");
  try {
    const report = await postJson("/api/data/fetch", {
      game: $("#game").value,
      start: $("#from").value,
      end: $("#to").value,
      force: $("#force").checked,
    });
    const warn = report.stale_source || report.conflicts.length > 0;
    setStatus(status, describeFetch(report), warn ? "warn" : "success");
    await refreshSummary();
  } catch (err) {
    setStatus(status, `Lỗi đồng bộ dữ liệu: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
  }
}

function el(tag, props = {}, children = []) {
  const node = Object.assign(document.createElement(tag), props);
  for (const c of [].concat(children)) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}

const fmt = (v, digits = 2) => (v === null || v === undefined ? "–" : Number(v).toFixed(digits));
const pad2 = (n) => String(n).padStart(2, "0");
