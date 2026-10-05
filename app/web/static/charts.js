"use strict";
// Minimal SVG charts: column (single or grouped) and line with crosshair.
// Colors come from CSS custom properties (--series-*, --chart-*), so light/dark follow the page.
// Every chart sits next to a table that holds the same values; tooltips enhance, never gate.

const Charts = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const PAD = { top: 16, right: 16, bottom: 34, left: 44 };
  const HEIGHT = 240;

  function svgEl(tag, attrs = {}, text) {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function niceTicks(min, max, count = 5) {
    if (min === max) max = min + 1;
    const span = max - min;
    const step0 = span / count;
    const mag = 10 ** Math.floor(Math.log10(step0));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || 10 * mag;
    const start = Math.floor(min / step) * step;
    const ticks = [];
    for (let v = start; v <= max + step * 0.5; v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }

  // ---- tooltip (one per page) ----
  let tip;
  function tooltip() {
    if (!tip) {
      tip = Object.assign(document.createElement("div"), { className: "chart-tip", role: "status" });
      tip.hidden = true;
      document.body.append(tip);
    }
    return tip;
  }
  function showTip(evt, title, rows) {
    const t = tooltip();
    t.replaceChildren();
    const head = document.createElement("div");
    head.className = "chart-tip-title";
    head.textContent = title;
    t.append(head);
    for (const r of rows) {
      const row = document.createElement("div");
      row.className = "chart-tip-row";
      if (r.color) {
        const key = document.createElement("span");
        key.className = "chart-tip-key";
        key.style.background = r.color;
        row.append(key);
      }
      const v = document.createElement("strong");
      v.textContent = r.value;
      const l = document.createElement("span");
      l.textContent = r.label;
      row.append(v, l);
      t.append(row);
    }
    t.hidden = false;
    const rect = evt.currentTarget.getBoundingClientRect ? evt.currentTarget.getBoundingClientRect() : null;
    const x = evt.clientX ?? (rect ? rect.left + rect.width / 2 : 0);
    const y = evt.clientY ?? (rect ? rect.top : 0);
    const w = t.offsetWidth;
    t.style.left = `${Math.min(window.innerWidth - w - 8, Math.max(8, x + 12))}px`;
    t.style.top = `${Math.max(8, y - t.offsetHeight - 12)}px`;
  }
  function hideTip() {
    if (tip) tip.hidden = true;
  }

  function cssVar(el, name) {
    return getComputedStyle(el).getPropertyValue(name).trim();
  }

  function frame(container, ariaLabel) {
    const width = Math.max(280, container.clientWidth || 600);
    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${HEIGHT}`, width, height: HEIGHT, role: "img", "aria-label": ariaLabel });
    container.replaceChildren(svg);
    return { svg, width, plotW: width - PAD.left - PAD.right, plotH: HEIGHT - PAD.top - PAD.bottom };
  }

  function yAxis(svg, width, plotH, scaleY, ticks, fmt) {
    const g = svgEl("g", { class: "chart-grid" });
    for (const t of ticks) {
      const y = PAD.top + scaleY(t);
      g.append(svgEl("line", { x1: PAD.left, x2: width - PAD.right, y1: y, y2: y }));
      g.append(svgEl("text", { x: PAD.left - 6, y: y + 4, "text-anchor": "end", class: "chart-tick" }, fmt(t)));
    }
    svg.append(g);
  }

  function refLine(svg, width, y, label, cls = "chart-ref") {
    svg.append(svgEl("line", { x1: PAD.left, x2: width - PAD.right, y1: y, y2: y, class: cls }));
    if (label) svg.append(svgEl("text", { x: width - PAD.right, y: y - 4, "text-anchor": "end", class: "chart-ref-label" }, label));
  }

  function legend(container, items) {
    const box = document.createElement("div");
    box.className = "chart-legend";
    for (const it of items) {
      const item = document.createElement("span");
      const key = document.createElement("span");
      key.className = `chart-legend-key ${it.shape || "rect"}`;
      key.style.background = it.color;
      item.append(key, document.createTextNode(it.label));
      box.append(item);
    }
    container.append(box);
  }

  /**
   * Column chart. series: [{label, values, colorVar}] (1 series → no legend box).
   * opts: categories, yFormat, refs [{value, label}], vlines [{at (category index, may be fractional), label}],
   *       labelEvery, tipTitle(i), tipExtra(i) → rows, ariaLabel, yMin
   */
  function columns(container, opts) {
    const { categories, series } = opts;
    const { svg, width, plotW, plotH } = frame(container, opts.ariaLabel || "Column chart");
    const all = series.flatMap((s) => s.values).concat((opts.refs || []).map((r) => r.value));
    const ticks = niceTicks(opts.yMin ?? 0, Math.max(...all));
    const yMax = ticks[ticks.length - 1];
    const yMin = ticks[0];
    const scaleY = (v) => plotH - ((v - yMin) / (yMax - yMin)) * plotH;
    const fmt = opts.yFormat || ((v) => String(v));
    yAxis(svg, width, plotH, scaleY, ticks, fmt);

    const band = plotW / categories.length;
    const groupGap = series.length > 1 ? Math.min(6, band * 0.2) : 0;
    const barW = Math.max(1, Math.min(24, (band - 2 - groupGap) / series.length - (series.length > 1 ? 2 : 0)));
    const groupW = barW * series.length + (series.length - 1) * 2;
    const r = Math.min(4, barW / 2);
    const colors = series.map((s) => cssVar(container, s.colorVar));

    // x labels
    const every = opts.labelEvery || Math.max(1, Math.ceil(categories.length / Math.floor(plotW / 28)));
    categories.forEach((c, i) => {
      if (i % every !== 0) return;
      svg.append(svgEl("text", { x: PAD.left + band * (i + 0.5), y: HEIGHT - PAD.bottom + 16, "text-anchor": "middle", class: "chart-tick" }, c));
    });
    svg.append(svgEl("line", { x1: PAD.left, x2: width - PAD.right, y1: PAD.top + plotH, y2: PAD.top + plotH, class: "chart-baseline" }));

    categories.forEach((c, i) => {
      const x0 = PAD.left + band * i + (band - groupW) / 2;
      series.forEach((s, si) => {
        const v = s.values[i];
        const top = PAD.top + scaleY(Math.max(v, yMin));
        const base = PAD.top + scaleY(yMin);
        const h = Math.max(0, base - top);
        const x = x0 + si * (barW + 2);
        // Rounded data end, square at the baseline.
        const rr = Math.min(r, h);
        const d = `M${x},${base} V${top + rr} Q${x},${top} ${x + rr},${top} H${x + barW - rr} Q${x + barW},${top} ${x + barW},${top + rr} V${base} Z`;
        svg.append(svgEl("path", { d, fill: colors[si], class: "chart-bar" }));
      });
      // Hit target: the whole band, taller than the mark.
      const hit = svgEl("rect", { x: PAD.left + band * i, y: PAD.top, width: band, height: plotH, class: "chart-hit", tabindex: 0 });
      const rows = () => [
        ...series.map((s, si) => ({ label: s.label, value: fmt2(s.values[i], opts.valueFormat || fmt), color: colors[si] })),
        ...(opts.tipExtra ? opts.tipExtra(i) : []),
      ];
      const title = opts.tipTitle ? opts.tipTitle(i) : c;
      hit.addEventListener("pointermove", (e) => showTip(e, title, rows()));
      hit.addEventListener("focus", (e) => showTip(e, title, rows()));
      hit.addEventListener("pointerleave", hideTip);
      hit.addEventListener("blur", hideTip);
      svg.append(hit);
    });

    for (const ref of opts.refs || []) refLine(svg, width, PAD.top + scaleY(ref.value), ref.label);
    for (const v of opts.vlines || []) {
      const x = PAD.left + band * (v.at + 0.5);
      svg.append(svgEl("line", { x1: x, x2: x, y1: PAD.top, y2: PAD.top + plotH, class: "chart-ref" }));
      svg.append(svgEl("text", { x: x + 4, y: PAD.top + 10, class: "chart-ref-label" }, v.label));
    }
    if (series.length > 1) legend(container, series.map((s, si) => ({ label: s.label, color: colors[si] })));
  }

  function fmt2(v, f) {
    return v === null || v === undefined ? "–" : f(v);
  }

  /**
   * Line chart with crosshair. series: [{label, values, colorVar, muted}], x: labels.
   * opts: yFormat, zero (draw a reference at 0 with label), ariaLabel
   */
  function lines(container, opts) {
    const { x, series } = opts;
    const { svg, width, plotW, plotH } = frame(container, opts.ariaLabel || "Line chart");
    const vals = series.flatMap((s) => s.values).filter((v) => v !== null && Number.isFinite(v));
    let lo = Math.min(...vals, opts.zero !== undefined ? opts.zero : Infinity);
    let hi = Math.max(...vals, opts.zero !== undefined ? opts.zero : -Infinity);
    const ticks = niceTicks(lo, hi);
    lo = ticks[0];
    hi = ticks[ticks.length - 1];
    const scaleY = (v) => plotH - ((v - lo) / (hi - lo || 1)) * plotH;
    const scaleX = (i) => PAD.left + (x.length > 1 ? (i / (x.length - 1)) * plotW : plotW / 2);
    const fmt = opts.yFormat || ((v) => String(v));
    yAxis(svg, width, plotH, scaleY, ticks, fmt);
    if (opts.zero !== undefined) refLine(svg, width, PAD.top + scaleY(opts.zero), opts.zeroLabel || "", "chart-zero");

    // x labels: first, last and a few evenly spaced
    const n = Math.min(x.length, Math.max(2, Math.floor(plotW / 110)));
    for (let k = 0; k < n; k++) {
      const i = Math.round((k / (n - 1 || 1)) * (x.length - 1));
      const anchor = k === 0 ? "start" : k === n - 1 ? "end" : "middle";
      svg.append(svgEl("text", { x: scaleX(i), y: HEIGHT - PAD.bottom + 16, "text-anchor": anchor, class: "chart-tick" }, x[i]));
    }

    const colors = series.map((s) => cssVar(container, s.colorVar));
    series.forEach((s, si) => {
      const pts = s.values.map((v, i) => (v === null ? null : `${scaleX(i)},${PAD.top + scaleY(v)}`)).filter(Boolean);
      svg.append(svgEl("polyline", { points: pts.join(" "), fill: "none", stroke: colors[si], class: s.muted ? "chart-line muted" : "chart-line" }));
    });
    // End dots + direct labels (selective: only the end).
    const ends = series.map((s, si) => ({ s, si, y: PAD.top + scaleY(s.values[s.values.length - 1]) })).sort((a, b) => a.y - b.y);
    let lastY = -Infinity;
    for (const e of ends) {
      const cx = scaleX(e.s.values.length - 1);
      svg.append(svgEl("circle", { cx, cy: e.y, r: 4, fill: colors[e.si], class: "chart-dot" }));
      if (e.y - lastY >= 12) {
        svg.append(svgEl("text", { x: cx - 8, y: e.y - 6, "text-anchor": "end", class: "chart-end-label" }, e.s.label));
        lastY = e.y;
      }
    }

    // Crosshair layer
    const cross = svgEl("line", { y1: PAD.top, y2: PAD.top + plotH, class: "chart-cross", visibility: "hidden" });
    svg.append(cross);
    const layer = svgEl("rect", { x: PAD.left, y: PAD.top, width: plotW, height: plotH, class: "chart-hit", tabindex: 0 });
    const at = (evt) => {
      const box = svg.getBoundingClientRect();
      const px = ((evt.clientX - box.left) / box.width) * width;
      return Math.max(0, Math.min(x.length - 1, Math.round(((px - PAD.left) / plotW) * (x.length - 1))));
    };
    const move = (evt, i) => {
      cross.setAttribute("x1", scaleX(i));
      cross.setAttribute("x2", scaleX(i));
      cross.setAttribute("visibility", "visible");
      const rows = series.map((s, si) => ({ label: s.label, value: fmt2(s.values[i], opts.valueFormat || fmt), color: colors[si] }));
      showTip(evt, opts.tipTitle ? opts.tipTitle(i) : x[i], rows);
    };
    layer.addEventListener("pointermove", (e) => move(e, at(e)));
    layer.addEventListener("focus", (e) => move(e, x.length - 1));
    const leave = () => {
      cross.setAttribute("visibility", "hidden");
      hideTip();
    };
    layer.addEventListener("pointerleave", leave);
    layer.addEventListener("blur", leave);
    svg.append(layer);
    legend(container, series.map((s, si) => ({ label: s.label, color: colors[si], shape: "line" })));
  }

  // Re-render on width change so text stays crisp (no scaling of a fixed viewBox).
  function responsive(container, render) {
    let lastW = 0;
    const ro = new ResizeObserver(() => {
      const w = container.clientWidth;
      if (w && Math.abs(w - lastW) > 4) {
        lastW = w;
        render();
      }
    });
    if (container._chartObserver) container._chartObserver.disconnect();
    container._chartObserver = ro;
    ro.observe(container);
    render();
  }

  return { columns, lines, responsive };
})();
