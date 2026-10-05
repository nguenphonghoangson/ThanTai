"use strict";
// Wiring: runs after the section scripts are loaded.
document.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([loadGames(), loadStrategies()]);
  applyPreset();
  $("#strategy").addEventListener("change", () => {
    applyPreset();
    onRescore();
  });
  for (const input of document.querySelectorAll("#weights input, #weights select")) input.addEventListener("change", onRescore);
  $("#scores-table").addEventListener("click", onScoresTableClick);
  $("#btn-generate").addEventListener("click", () => onGenerate($("#seed").value));
  $("#btn-again").addEventListener("click", () => onGenerate(null));
  $("#btn-seed").addEventListener("click", () => onGenerate($("#seed-change").value));
  $("#btn-reproduce").addEventListener("click", onReproduce);
  $("#sessions-table").addEventListener("click", onSessionClick);
  $("#btn-backtest").addEventListener("click", onBacktest);
  $("#number-metric").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-metric]");
    if (!b || !analysis) return;
    numberMetric = b.dataset.metric;
    renderNumberChart();
  });
  $("#bt-runs").addEventListener("click", onBacktestRunClick);
  loadBacktests().catch(() => {});
  loadSessions().catch(() => {});
  $("#game").addEventListener("change", () => {
    setStatus($("#fetch-status"), "");
    $("#stats-section").hidden = true;
    $("#scores-section").hidden = true;
    scoring = null;
    selectedNumber = null;
    session = null;
    $("#combos-section").hidden = true;
    $("#bt-result").hidden = true;
    backtestShown = null;
    loadSessions().catch(() => {});
    loadBacktests().catch(() => {});
    refreshSummary();
  });
  $("#btn-fetch").addEventListener("click", onFetch);
  $("#btn-analyze").addEventListener("click", onAnalyze);
  $("#numbers-table thead").addEventListener("click", onSortClick);
  refreshSummary();
});
