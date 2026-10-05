"use strict";
// Shared helpers, API calls, game/data summary and fetch.

const $ = (sel) => document.querySelector(sel);

async function requestJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail;
    throw new Error(detail || `${res.status} ${res.statusText}`);
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
  el.textContent = text;
  el.classList.toggle("error", kind === "error");
  el.classList.toggle("warn", kind === "warn");
}

function renderGameInfo(key) {
  const g = gamesByKey[key];
  if (!g) return;
  setStatus(
    $("#game-info"),
    `${g.name}: ${g.numbers_per_draw} numbers from ${g.min_number}–${g.max_number}. ` +
      `Low ${g.low_range[0]}–${g.low_range[1]}, high ${g.high_range[0]}–${g.high_range[1]}` +
      (g.has_bonus_number ? ". Bonus ball stored but excluded from analysis." : "."),
  );
}

function renderQuality(s) {
  const notes = [];
  if (s.total_draws && s.missing_before_first > 0) {
    notes.push(`Draws #1–#${s.missing_before_first} are not available from the source (first stored: #${s.first_draw_id}).`);
  }
  if (s.missing_draw_count > 0) {
    const ids = s.missing_draw_ids.map((n) => `#${n}`).join(", ");
    notes.push(`${s.missing_draw_count} draw(s) missing inside the stored range: ${ids}${s.missing_draw_count > s.missing_draw_ids.length ? ", …" : ""}.`);
  }
  const list = $("#data-quality");
  list.replaceChildren(...notes.map((n) => Object.assign(document.createElement("li"), { textContent: n })));
  list.hidden = notes.length === 0;
}

async function refreshSummary() {
  const key = $("#game").value;
  renderGameInfo(key);
  const box = $("#data-summary");
  const field = (name) => box.querySelector(`[data-field="${name}"]`);
  try {
    const s = await getJson(`/api/data/summary?game=${encodeURIComponent(key)}`);
    field("game").textContent = gamesByKey[key]?.name ?? s.game;
    field("total_draws").textContent = s.total_draws.toLocaleString();
    field("first_date").textContent = s.first_date ? `${s.first_date} (#${s.first_draw_id})` : "—";
    field("last_date").textContent = s.last_date ? `${s.last_date} (#${s.last_draw_id})` : "—";
    renderQuality(s);
  } catch (err) {
    setStatus($("#game-info"), err.message, "error");
  }
}

function describeFetch(r) {
  if (r.up_to_date) return `Already cached for ${r.requested[0]} → ${r.requested[1]}. Nothing fetched.`;
  const parts = [
    `Fetched ${r.fetched_ranges.length} range(s): received ${r.received}, inserted ${r.inserted}, already stored ${r.unchanged}.`,
  ];
  if (r.conflicts.length) parts.push(`${r.conflicts.length} conflicting draw(s) kept as stored: ${r.conflicts.slice(0, 5).join(", ")}.`);
  if (r.rejected.length) parts.push(`${r.rejected.length} source record(s) rejected: ${r.rejected.slice(0, 3).join("; ")}.`);
  if (r.stale_source) parts.push("Source unreachable; used an expired cached copy.");
  return parts.join(" ");
}

async function onFetch() {
  const btn = $("#btn-fetch");
  const status = $("#fetch-status");
  btn.disabled = true;
  setStatus(status, "Fetching…");
  try {
    const report = await postJson("/api/data/fetch", {
      game: $("#game").value,
      start: $("#from").value,
      end: $("#to").value,
      force: $("#force").checked,
    });
    const warn = report.stale_source || report.conflicts.length || report.rejected.length;
    setStatus(status, describeFetch(report), warn ? "warn" : undefined);
    await refreshSummary();
  } catch (err) {
    setStatus(status, `Fetch failed: ${err.message}`, "error");
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
