"use strict";
// Khởi tạo và điều phối các sự kiện chính (Main Controller).

function refreshIcons() {
  if (window.lucide && typeof lucide.createIcons === "function") {
    lucide.createIcons();
  }
}

function switchTab(targetPanelId) {
  const buttons = document.querySelectorAll(".tab-btn");
  const panels = document.querySelectorAll(".tab-panel");

  buttons.forEach((btn) => {
    const isTarget = btn.dataset.target === targetPanelId;
    btn.classList.toggle("active", isTarget);
    btn.setAttribute("aria-selected", String(isTarget));
  });

  panels.forEach((panel) => {
    const isTarget = panel.id === targetPanelId;
    panel.classList.toggle("active", isTarget);
  });

  refreshIcons();

  // Kích hoạt vẽ lại biểu đồ SVG tương ứng với độ rộng container hiện tại
  setTimeout(() => {
    window.dispatchEvent(new Event("resize"));
    if (targetPanelId === "panel-analysis" && analysis) {
      if (typeof renderNumberChart === "function") renderNumberChart();
      if (typeof renderDistributionCharts === "function") renderDistributionCharts();
    } else if (targetPanelId === "panel-generation" && scoring) {
      if (typeof renderScoreChart === "function") renderScoreChart();
    } else if (targetPanelId === "panel-backtest" && backtestShown) {
      if (typeof renderBacktestChart === "function") renderBacktestChart(backtestShown);
    }
  }, 60);
}

function initTheme() {
  const toggleBtn = $("#theme-toggle");
  if (!toggleBtn) return;
  toggleBtn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "light";
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    if (next === "dark") {
      document.documentElement.classList.add("dark");
      document.documentElement.classList.remove("light");
    } else {
      document.documentElement.classList.add("light");
      document.documentElement.classList.remove("dark");
    }
    localStorage.setItem("vietlott_theme", next);
    refreshIcons();
    window.dispatchEvent(new Event("resize"));
  });
}

function initGamePillSwitcher() {
  const container = $("#game-pill-group");
  const gameSelect = $("#game");
  if (!container || !gameSelect) return;

  container.addEventListener("click", (e) => {
    const btn = e.target.closest(".game-pill-btn");
    if (!btn || !btn.dataset.game) return;
    if (gameSelect.value !== btn.dataset.game) {
      gameSelect.value = btn.dataset.game;
      gameSelect.dispatchEvent(new Event("change"));
    }
  });

  function updatePillStyles() {
    const current = gameSelect.value;
    container.querySelectorAll(".game-pill-btn").forEach((btn) => {
      const isActive = btn.dataset.game === current;
      btn.classList.toggle("active", isActive);
    });
  }

  gameSelect.addEventListener("change", updatePillStyles);
  updatePillStyles();
}

function initDatePresets() {
  const container = $("#date-presets");
  if (!container) return;
  container.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-preset]");
    if (!btn) return;
    const toInput = $("#to");
    const fromInput = $("#from");
    const toDate = toInput && toInput.value ? new Date(toInput.value) : new Date();
    
    if (btn.dataset.preset === "1y") {
      const d = new Date(toDate);
      d.setFullYear(d.getFullYear() - 1);
      fromInput.value = d.toISOString().slice(0, 10);
    } else if (btn.dataset.preset === "3y") {
      const d = new Date(toDate);
      d.setFullYear(d.getFullYear() - 3);
      fromInput.value = d.toISOString().slice(0, 10);
    } else if (btn.dataset.preset === "all") {
      fromInput.value = "2016-01-01";
    }
  });
}

function initTabs() {
  const navTabs = document.querySelector(".nav-tabs");
  if (!navTabs) return;
  navTabs.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab-btn");
    if (!btn || !btn.dataset.target) return;
    switchTab(btn.dataset.target);
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  initDatePresets();
  initTabs();
  initGamePillSwitcher();

  await Promise.all([loadGames(), loadStrategies()]);
  applyPreset();
  refreshIcons();

  const stratEl = $("#strategy");
  if (stratEl) {
    stratEl.addEventListener("change", () => {
      applyPreset();
      onRescore();
    });
  }

  for (const input of document.querySelectorAll("#weights input, #weights select")) {
    input.addEventListener("change", onRescore);
  }

  const scoresTable = $("#scores-table");
  if (scoresTable) scoresTable.addEventListener("click", onScoresTableClick);

  const btnGen = $("#btn-generate");
  if (btnGen) {
    btnGen.addEventListener("click", () => {
      onGenerate($("#seed").value);
    });
  }

  const btnAgain = $("#btn-again");
  if (btnAgain) btnAgain.addEventListener("click", () => onGenerate(null));

  const btnSeed = $("#btn-seed");
  if (btnSeed) btnSeed.addEventListener("click", () => onGenerate($("#seed-change").value));

  const btnRep = $("#btn-reproduce");
  if (btnRep) btnRep.addEventListener("click", onReproduce);

  const sessionsTable = $("#sessions-table");
  if (sessionsTable) sessionsTable.addEventListener("click", onSessionClick);

  const btnBt = $("#btn-backtest");
  if (btnBt) btnBt.addEventListener("click", onBacktest);

  const numMetric = $("#number-metric");
  if (numMetric) {
    numMetric.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-metric]");
      if (!b || !analysis) return;
      numberMetric = b.dataset.metric;
      renderNumberChart();
    });
  }

  const btRuns = $("#bt-runs");
  if (btRuns) btRuns.addEventListener("click", onBacktestRunClick);

  loadBacktests().catch(() => {});
  loadSessions().catch(() => {});

  const gameEl = $("#game");
  if (gameEl) {
    gameEl.addEventListener("change", () => {
      setStatus($("#fetch-status"), "");
      const statsSection = $("#stats-section");
      if (statsSection) statsSection.hidden = true;
      const emptyState = $("#analysis-empty-state");
      if (emptyState) emptyState.hidden = false;
      const scoresSection = $("#scores-section");
      if (scoresSection) scoresSection.hidden = true;
      scoring = null;
      selectedNumber = null;
      session = null;
      const combosSection = $("#combos-section");
      if (combosSection) combosSection.hidden = true;
      const btResult = $("#bt-result");
      if (btResult) btResult.hidden = true;
      backtestShown = null;
      loadSessions().catch(() => {});
      loadBacktests().catch(() => {});
      refreshSummary();
      // Tự động phân tích thống kê ngầm cho trò chơi mới
      onAnalyze(true).catch(() => {});
      refreshIcons();
    });
  }

  const btnFetch = $("#btn-fetch");
  if (btnFetch) btnFetch.addEventListener("click", () => onFetch());

  const btnAnalyze = $("#btn-analyze");
  if (btnAnalyze) btnAnalyze.addEventListener("click", () => onAnalyze(false));

  const numThead = $("#numbers-table thead");
  if (numThead) numThead.addEventListener("click", onSortClick);

  // Resize listener tự động co giãn biểu đồ SVG khi thay đổi kích cỡ màn hình
  let resizeTimeout;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(() => {
      const activePanel = document.querySelector(".tab-panel.active");
      if (!activePanel) return;
      if (activePanel.id === "panel-analysis" && analysis) {
        if (typeof renderNumberChart === "function") renderNumberChart();
        if (typeof renderDistributionCharts === "function") renderDistributionCharts();
      } else if (activePanel.id === "panel-generation" && scoring) {
        if (typeof renderScoreChart === "function") renderScoreChart();
      } else if (activePanel.id === "panel-backtest" && backtestShown) {
        if (typeof renderBacktestChart === "function") renderBacktestChart(backtestShown);
      }
    }, 150);
  });

  refreshSummary();
  // Khởi động phân tích ngầm ngay khi tải trang để các phân hệ sẵn sàng
  onAnalyze(true).catch(() => {});
});
