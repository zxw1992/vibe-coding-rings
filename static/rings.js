// ── Language management ──

const LANG_KEY = "vcc_lang";
let currentLang = localStorage.getItem(LANG_KEY) || "en";

function applyLang(lang, syncServer = false) {
  currentLang = lang;
  localStorage.setItem(LANG_KEY, lang);
  document.documentElement.setAttribute("data-lang", lang);

  const btn = document.getElementById("lang-toggle");
  btn.textContent = lang === "zh" ? "EN" : "中文";

  document.querySelectorAll(".zh").forEach(el => {
    el.style.display = lang === "zh" ? "" : "none";
  });
  document.querySelectorAll(".en").forEach(el => {
    el.style.display = lang === "en" ? "" : "none";
  });

  applyHistoryLabels();

  if (syncServer) {
    fetch("/api/lang", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang }),
    }).catch(() => {});
  }
}

document.getElementById("lang-toggle").addEventListener("click", () => {
  applyLang(currentLang === "zh" ? "en" : "zh", true);  // sync to server
});

// Apply on load from localStorage only (no server sync)
applyLang(currentLang, false);


// ── Ring geometry (main rings) ──

const MAIN_RINGS = [
  { id: "tokens", svgId: "ring-tokens", overId: "ring-tokens-over", tipId: "ring-tokens-tip", r: 120, color: "#FF375F" },
  { id: "focus",  svgId: "ring-focus",  overId: "ring-focus-over",  tipId: "ring-focus-tip",  r: 90,  color: "#30D158" },
  { id: "tools",  svgId: "ring-tools",  overId: "ring-tools-over",  tipId: "ring-tools-tip",  r: 60,  color: "#0A84FF" },
];

MAIN_RINGS.forEach(ring => {
  ring.circ = 2 * Math.PI * ring.r;
  const el = document.getElementById(ring.svgId);
  el.style.strokeDasharray = ring.circ;
  el.style.strokeDashoffset = ring.circ;
  const overEl = document.getElementById(ring.overId);
  overEl.style.transition = "none";           // prevent dashoffset from animating from HTML attr
  overEl.style.strokeDasharray = ring.circ;
  overEl.style.strokeDashoffset = ring.circ;
  requestAnimationFrame(() => {
    overEl.style.visibility = "visible";      // reveal only after dasharray/offset are set
    overEl.style.transition = "";             // restore class transitions
  });
});

// Mini ring sizes (for history)
const MINI = { r: [28, 21, 14], stroke: 7, size: 72 };
MINI.circs = MINI.r.map(r => 2 * Math.PI * r);


// ── Tooltip ──

const tooltip = document.getElementById("tooltip");
let tooltipHideTimer = null;

function showTooltip(html, x, y) {
  clearTimeout(tooltipHideTimer);
  tooltip.innerHTML = html;
  tooltip.classList.add("visible");
  positionTooltip(x, y);
}

function hideTooltip() {
  tooltipHideTimer = setTimeout(() => tooltip.classList.remove("visible"), 80);
}

function positionTooltip(x, y) {
  const tw = tooltip.offsetWidth + 16;
  const th = tooltip.offsetHeight + 16;
  let left = x + 14;
  let top  = y - 10;
  if (left + tw > window.innerWidth)  left = x - tw + 14;
  if (top  + th > window.innerHeight) top  = y - th;
  tooltip.style.left = left + "px";
  tooltip.style.top  = top  + "px";
}

function buildTooltipHtml(day, goals, lang) {
  const zh = lang === "zh";
  const pct = v => Math.round(v * 100) + "%";
  const date = new Date(day.date + "T12:00:00").toLocaleDateString(
    zh ? "zh-CN" : "en-US", { month: "short", day: "numeric" }
  );
  return `
    <div class="tooltip-date">${date}</div>
    <div class="tooltip-row">
      <span style="color:#FF375F">${zh ? "消耗" : "Consume"}</span>
      <span class="t-val">${fmtTokens(day.tokens)} <span style="color:var(--text-muted)">${pct(day.token_pct)}</span></span>
    </div>
    <div class="tooltip-row">
      <span style="color:#30D158">${zh ? "专注" : "Focus"}</span>
      <span class="t-val">${Math.round(day.focus_min)}min <span style="color:var(--text-muted)">${pct(day.focus_pct)}</span></span>
    </div>
    <div class="tooltip-row">
      <span style="color:#0A84FF">${zh ? "行动" : "Action"}</span>
      <span class="t-val">${day.tool_calls} <span style="color:var(--text-muted)">${pct(day.tool_pct)}</span></span>
    </div>`;
}


// ── Helpers ──

function fmtTokens(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(0) + "K";
  return String(n);
}

function fmtGoalTokens(n) {
  if (n >= 1_000_000) return (n / 1_000_000 % 1 === 0 ? (n / 1_000_000).toFixed(0) : (n / 1_000_000).toFixed(1)) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(0) + "K";
  return String(n);
}

function fmtPct(pct) {
  return Math.round(pct * 100) + "%";
}

function dayAbbr(dateStr, lang) {
  const d = new Date(dateStr + "T12:00:00");
  if (lang === "zh") {
    const map = ["日","一","二","三","四","五","六"];
    return "周" + map[d.getDay()];
  }
  return d.toLocaleDateString("en-US", { weekday: "short" }).toUpperCase();
}

function isToday(dateStr) {
  return dateStr === new Date().toLocaleDateString('en-CA');
}

function updateSliderTrack(el) {
  const min = parseFloat(el.min);
  const max = parseFloat(el.max);
  const pct = ((parseFloat(el.value) - min) / (max - min)) * 100;
  el.style.setProperty("--pct", Math.max(2, pct) + "%");
}


// ── Main ring animation ──

function setRing(ring, pct) {
  const el     = document.getElementById(ring.svgId);
  const overEl = document.getElementById(ring.overId);
  const tipEl  = document.getElementById(ring.tipId);

  const mainPct = Math.min(pct, 1.0);
  const overPct = pct > 1.0 ? Math.min(pct - 1.0, 1.0) : 0;

  requestAnimationFrame(() => {
    el.style.strokeDashoffset    = ring.circ * (1 - mainPct);
    overEl.style.strokeDashoffset = ring.circ * (1 - overPct);
  });

  // Tip tracks the leading edge: overflow arc when lapping, main arc otherwise
  const tipPct = pct > 1.0 ? overPct : mainPct;
  const angle  = 2 * Math.PI * tipPct;
  tipEl.setAttribute("cx", (140 + ring.r * Math.cos(angle)).toFixed(2));
  tipEl.setAttribute("cy", (140 + ring.r * Math.sin(angle)).toFixed(2));
  tipEl.style.opacity = mainPct > 0.02 ? "1" : "0";

  if (pct >= 1.0) {
    el.classList.add("ring-glow");
    el.style.color = ring.color;
    overEl.classList.add("ring-glow");
    overEl.style.color = ring.color;
  } else {
    el.classList.remove("ring-glow");
    overEl.classList.remove("ring-glow");
  }
}


// ── Today update ──

let _todayData = null;

function updateToday(data) {
  _todayData = data;
  const { metrics, streak, goals } = data;

  // Date
  const d = new Date(metrics.date + "T12:00:00");
  document.getElementById("date-month").textContent =
    d.toLocaleDateString("en-US", { month: "short" }).toUpperCase();
  document.getElementById("date-day").textContent = d.getDate();

  // Streak
  document.getElementById("streak-count").textContent = streak;

  // Tokens
  setRing(MAIN_RINGS[0], metrics.token_pct);
  document.getElementById("tokens-val").textContent = fmtTokens(metrics.tokens);
  document.getElementById("tokens-goal-str").textContent = ` / ${fmtGoalTokens(goals.tokens)} tokens`;
  document.getElementById("tokens-pct").textContent = fmtPct(metrics.token_pct);

  // Focus
  setRing(MAIN_RINGS[1], metrics.focus_pct);
  document.getElementById("focus-val").textContent = Math.round(metrics.focus_min) + " min";
  document.getElementById("focus-goal-str").textContent = ` / ${goals.focus_min} min`;
  document.getElementById("focus-pct").textContent = fmtPct(metrics.focus_pct);

  // Tools
  setRing(MAIN_RINGS[2], metrics.tool_pct);
  document.getElementById("tools-val").textContent = metrics.tool_calls + " calls";
  document.getElementById("tools-goal-str").textContent = ` / ${goals.tool_calls} calls`;
  document.getElementById("tools-pct").textContent = fmtPct(metrics.tool_pct);

  // Sync goal inputs
  syncGoalInputs(goals);
}

// ── Main ring hover tooltips ──

MAIN_RINGS.forEach(ring => {
  const el = document.getElementById(ring.svgId);
  el.addEventListener("mousemove", e => {
    if (!_todayData) return;
    showTooltip(buildTooltipHtml(_todayData.metrics, _todayData.goals, currentLang), e.clientX, e.clientY);
  });
  el.addEventListener("mouseleave", hideTooltip);
});

// Also on ring-stat rows
document.querySelectorAll(".ring-stat").forEach(row => {
  row.addEventListener("mousemove", e => {
    if (!_todayData) return;
    showTooltip(buildTooltipHtml(_todayData.metrics, _todayData.goals, currentLang), e.clientX, e.clientY);
  });
  row.addEventListener("mouseleave", hideTooltip);
});


// ── History mini rings ──

let _historyData = [];

function buildMiniSVG(day) {
  const pcts = [day.token_pct, day.focus_pct, day.tool_pct];
  const colors = ["#FF375F", "#30D158", "#0A84FF"];
  const cx = MINI.size / 2;
  const cy = MINI.size / 2;

  let tracks = "";
  let arcs   = "";

  MINI.r.forEach((r, i) => {
    const circ = MINI.circs[i];
    const offset = circ * (1 - Math.min(pcts[i], 1.0));
    const glow = pcts[i] >= 1.0 ? `filter: drop-shadow(0 0 5px ${colors[i]});` : "";

    tracks += `<circle class="mini-ring-track" cx="${cx}" cy="${cy}" r="${r}"
      stroke="${colors[i]}" stroke-opacity="0.15" stroke-width="${MINI.stroke}" />`;

    arcs += `<circle class="mini-ring-progress" cx="${cx}" cy="${cy}" r="${r}"
      stroke="${colors[i]}" stroke-width="${MINI.stroke}"
      stroke-dasharray="${circ}" stroke-dashoffset="${circ}"
      data-offset="${offset}" style="${glow}" />`;
  });

  return `<svg class="history-day-svg" width="${MINI.size}" height="${MINI.size}"
    viewBox="0 0 ${MINI.size} ${MINI.size}">${tracks}${arcs}</svg>`;
}

function updateHistory(days) {
  _historyData = days;
  const container = document.getElementById("history-rings");
  container.innerHTML = "";

  days.forEach(day => {
    const today = isToday(day.date);
    const col = document.createElement("div");
    col.className = "history-day";

    col.innerHTML = buildMiniSVG(day);

    const label = document.createElement("div");
    label.className = "history-day-label" + (today ? " today-label" : "");
    label.setAttribute("data-date", day.date);
    // Labels set by applyHistoryLabels()
    col.appendChild(label);

    // Click → date detail page
    col.addEventListener("click", () => { hideTooltip(); showDateDetailPage(day.date); });

    // Hover tooltip
    col.addEventListener("mousemove", e => {
      showTooltip(buildTooltipHtml(day, null, currentLang), e.clientX, e.clientY);
    });
    col.addEventListener("mouseleave", hideTooltip);

    container.appendChild(col);

    // Animate arcs after DOM insertion
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        col.querySelectorAll(".mini-ring-progress").forEach(arc => {
          arc.style.strokeDashoffset = arc.dataset.offset;
        });
      });
    });
  });

  applyHistoryLabels();
}

function applyHistoryLabels() {
  document.querySelectorAll(".history-day-label[data-date]").forEach(el => {
    const dateStr = el.dataset.date;
    if (isToday(dateStr)) {
      el.textContent = currentLang === "zh" ? "今天" : "Today";
    } else {
      el.textContent = dayAbbr(dateStr, currentLang);
    }
  });
}


// ── Goals: slider + number input sync ──

// scale = factor between the number input's display unit and raw value
// tokens: display in M (scale=1e6), others: raw (scale=1)
const GOAL_CONFIGS = [
  { slider: "goal-tokens", num: "goal-tokens-num", scale: 1_000_000, min: 100_000, sliderMax: 50_000_000 },
  { slider: "goal-focus",  num: "goal-focus-num",  scale: 1,         min: 15,      sliderMax: 1440       },
  { slider: "goal-tools",  num: "goal-tools-num",  scale: 1,         min: 1,       sliderMax: 500        },
];

// raw → display string for number input
function _numDisplay(rawVal, scale) {
  if (scale === 1) return String(rawVal);
  const v = rawVal / scale;
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

// display string → raw value
function _numParse(displayStr, scale) {
  return Math.round(parseFloat(displayStr) * scale) || 0;
}

async function doPostGoals() {
  const tokens    = _numParse(document.getElementById("goal-tokens-num").value, 1_000_000);
  const focus_min = parseInt(document.getElementById("goal-focus-num").value);
  const tool_calls = parseInt(document.getElementById("goal-tools-num").value);
  try {
    await fetch("/api/goals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tokens, focus_min, tool_calls }),
    });
    await refresh();
  } catch (e) {
    console.error("Failed to save goals", e);
  }
}

function syncGoalInputs(goals) {
  const rawVals = [goals.tokens, goals.focus_min, goals.tool_calls];
  GOAL_CONFIGS.forEach((cfg, i) => {
    const slider = document.getElementById(cfg.slider);
    const numEl  = document.getElementById(cfg.num);
    const raw = rawVals[i];
    slider.value = Math.min(raw, cfg.sliderMax);
    numEl.value  = _numDisplay(raw, cfg.scale);
    updateSliderTrack(slider);
  });
}

GOAL_CONFIGS.forEach(cfg => {
  const slider = document.getElementById(cfg.slider);
  const numEl  = document.getElementById(cfg.num);

  // Slider moves → update number display
  slider.addEventListener("input", () => {
    numEl.value = _numDisplay(parseFloat(slider.value), cfg.scale);
    updateSliderTrack(slider);
  });
  slider.addEventListener("change", doPostGoals);

  // Typing in number box → update slider position (visual only)
  numEl.addEventListener("input", () => {
    const raw = _numParse(numEl.value, cfg.scale);
    if (raw >= cfg.min) {
      slider.value = Math.min(raw, cfg.sliderMax);
      updateSliderTrack(slider);
    }
  });

  // Enter key → confirm immediately
  numEl.addEventListener("keydown", e => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const raw = _numParse(numEl.value, cfg.scale);
    if (raw >= cfg.min) doPostGoals();
    else numEl.value = _numDisplay(parseFloat(slider.value), cfg.scale); // revert
  });
});


// ── Agent chips ──────────────────────────────────────────────────────────────

const AGENT_COLORS = {
  claude_code: "#FF375F",
  codex:       "#10A37F",
  gemini:      "#4285F4",
  opencode:    "#8B5CF6",
};

let _agentsData = [];

function _hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function renderAgentChips() {
  const container = document.getElementById("agent-chips");
  container.innerHTML = "";
  _agentsData.forEach(agent => {
    const color = AGENT_COLORS[agent.id] || "#8E8E93";
    const chip = document.createElement("button");

    if (!agent.available) {
      chip.className = "agent-chip unavailable";
      chip.disabled = true;
      chip.title = `${agent.label} not installed (${agent.dir})`;
    } else if (agent.enabled) {
      chip.className = "agent-chip enabled";
      chip.style.borderColor  = color;
      chip.style.color        = color;
      chip.style.background   = _hexToRgba(color, 0.12);
    } else {
      chip.className = "agent-chip disabled";
    }

    chip.innerHTML = `<span class="agent-chip-dot"></span>${agent.label}`;

    if (agent.available) {
      chip.addEventListener("click", async () => {
        const currentEnabled = _agentsData.filter(a => a.enabled).map(a => a.id);
        const newEnabled = agent.enabled
          ? currentEnabled.filter(id => id !== agent.id)
          : [...currentEnabled, agent.id];
        if (newEnabled.length === 0) return;   // must keep at least one
        try {
          await fetch("/api/agents", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: newEnabled }),
          });
          await loadAgents();
          await refresh();
        } catch (e) {
          console.error("Failed to toggle agent", e);
        }
      });
    }
    container.appendChild(chip);
  });
}

async function loadAgents() {
  try {
    _agentsData = await fetch("/api/agents").then(r => r.json());
    renderAgentChips();
  } catch (e) {
    console.error("Failed to load agents", e);
  }
}


// ── Main refresh ──

async function refresh() {
  try {
    const [todayData, historyData] = await Promise.all([
      fetch("/api/today").then(r => r.json()),
      fetch("/api/history").then(r => r.json()),
    ]);
    updateToday(todayData);
    updateHistory(historyData);
    applyHistoryLabels();
    document.getElementById("last-updated").textContent =
      new Date().toLocaleTimeString();
  } catch (e) {
    console.error("Refresh failed", e);
  }
}

// Initial load
setTimeout(() => { loadAgents(); refresh(); }, 100);

// Auto-refresh every 60 seconds
setInterval(refresh, 60_000);


// ═══════════════════════════════════════════════════
// ── Detail page ──
// ═══════════════════════════════════════════════════

const METRIC_META = {
  tokens: {
    zhName: "消耗",
    enName: "Consume",
    color: "#FF375F",
    fmtVal:  v => fmtTokens(v),
    fmtGoal: v => fmtGoalTokens(v) + " tokens",
  },
  focus: {
    zhName: "专注",
    enName: "Focus",
    color: "#30D158",
    fmtVal:  v => Math.round(v) + " min",
    fmtGoal: v => v + " min",
  },
  tools: {
    zhName: "行动",
    enName: "Action",
    color: "#0A84FF",
    fmtVal:  v => v + " calls",
    fmtGoal: v => v + " calls",
  },
};

let _currentDetailMetric = null;

function showDetailPage(metric) {
  _currentDetailMetric = metric;
  const meta = METRIC_META[metric];
  const page = document.getElementById("page-detail");

  // Color theme
  const miniRing = document.getElementById("detail-mini-ring");
  const arc = document.getElementById("detail-ring-arc");
  miniRing.style.color = meta.color;
  arc.style.stroke = meta.color;
  arc.style.strokeDashoffset = "144.51"; // reset

  document.getElementById("detail-title").textContent =
    currentLang === "zh" ? meta.zhName : meta.enName;
  document.getElementById("detail-title").style.color = meta.color;

  // Show page
  page.classList.add("visible");
  page.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";

  // Apply lang on detail page elements
  page.querySelectorAll(".zh").forEach(el => {
    el.style.display = currentLang === "zh" ? "" : "none";
  });
  page.querySelectorAll(".en").forEach(el => {
    el.style.display = currentLang === "en" ? "" : "none";
  });

  // Fetch and render
  const today = new Date().toLocaleDateString('en-CA');
  fetch(`/api/hourly?metric=${metric}&d=${today}`)
    .then(r => r.json())
    .then(data => renderDetail(data, meta))
    .catch(e => console.error("Detail fetch failed", e));
}

function hideDetailPage() {
  const page = document.getElementById("page-detail");
  page.classList.remove("visible");
  page.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  _currentDetailMetric = null;
}

function renderDetail(data, meta) {
  const { hourly, total, goal } = data;
  const pct = goal > 0 ? total / goal : 0;
  const CIRC = 144.51;

  // Mini ring
  const arc = document.getElementById("detail-ring-arc");
  requestAnimationFrame(() => {
    arc.style.transition = "stroke-dashoffset 1s cubic-bezier(0.4,0,0.2,1)";
    arc.style.strokeDashoffset = CIRC * (1 - Math.min(pct, 1));
    if (pct >= 1) arc.style.filter = `drop-shadow(0 0 8px ${meta.color})`;
  });
  document.getElementById("detail-mini-pct").textContent = fmtPct(pct);

  // Values header
  document.getElementById("detail-val-current").textContent = meta.fmtVal(total);
  document.getElementById("detail-val-goal").textContent = meta.fmtGoal(goal);
  document.getElementById("detail-summary-val").textContent = meta.fmtVal(total);

  renderHourlyChart(document.getElementById("detail-chart"), hourly, meta.color, meta.fmtVal);
}

function renderHourlyChart(svgEl, hourly, color, fmtVal, gradId = "hbargrad") {
  svgEl.innerHTML = "";
  const svg = svgEl;

  // Layout
  const cx0 = 28, cxEnd = 472, cy0 = 14, cyAxis = 148;
  const cw = cxEnd - cx0;
  const ch = cyAxis - cy0;
  const slotW = cw / 24;
  const barW = Math.max(slotW * 0.58, 5);

  const maxVal = Math.max(...hourly, 1);

  const NS = "http://www.w3.org/2000/svg";
  const FONT = "-apple-system,BlinkMacSystemFont,sans-serif";
  const mk = (tag, attrs, text) => {
    const e = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
    if (text !== undefined) e.textContent = text;
    return e;
  };

  // ── Gradient ──────────────────────────────────────────────────────────────
  const defs = mk("defs", {});
  const gradHovId = gradId + "-hov";
  const grad = mk("linearGradient", { id: gradId, x1: "0", y1: "1", x2: "0", y2: "0" });
  grad.appendChild(mk("stop", { offset: "0%",   "stop-color": color, "stop-opacity": "0.18" }));
  grad.appendChild(mk("stop", { offset: "100%", "stop-color": color, "stop-opacity": "1.0"  }));
  defs.appendChild(grad);
  // Hover highlight gradient (brighter)
  const gradHov = mk("linearGradient", { id: gradHovId, x1: "0", y1: "1", x2: "0", y2: "0" });
  gradHov.appendChild(mk("stop", { offset: "0%",   "stop-color": color, "stop-opacity": "0.4" }));
  gradHov.appendChild(mk("stop", { offset: "100%", "stop-color": "#FFFFFF", "stop-opacity": "1.0" }));
  defs.appendChild(gradHov);
  svg.appendChild(defs);


  // ── Bars ─────────────────────────────────────────────────────────────────
  const bars = [];
  hourly.forEach((val, i) => {
    const x = cx0 + i * slotW + (slotW - barW) / 2;
    const barH = (val / maxVal) * ch;
    const bar = mk("rect", {
      x, y: cyAxis - barH,
      width: barW, height: barH,
      rx: Math.min(3, barW / 2),
      fill: val > 0 ? `url(#${gradId})` : "none",
      opacity: "0",
      style: "cursor: default;",
    });
    bar._val = val;
    bars.push(bar);
    svg.appendChild(bar);
  });

  // ── Axis line ─────────────────────────────────────────────────────────────
  svg.appendChild(mk("line", {
    x1: cx0, y1: cyAxis, x2: cxEnd, y2: cyAxis,
    stroke: "#3A3A3C", "stroke-width": "1",
  }));

  // ── X-axis labels ─────────────────────────────────────────────────────────
  [0, 6, 12, 18, 23].forEach(h => {
    const x = cx0 + (h + 0.5) * slotW;
    svg.appendChild(mk("text", {
      x, y: cyAxis + 14, "text-anchor": "middle",
      fill: "#8E8E93", "font-size": "10", "font-family": FONT,
    }, `${String(h).padStart(2, "0")}:00`));
  });

  // ── Invisible hit areas + hover tooltip ──────────────────────────────────
  hourly.forEach((val, i) => {
    const hitX = cx0 + i * slotW;
    const hit = mk("rect", {
      x: hitX, y: cy0,
      width: slotW, height: cyAxis - cy0 + 10,
      fill: "transparent",
      style: "cursor: crosshair;",
    });

    const bar = bars[i];

    hit.addEventListener("mouseenter", () => {
      if (val > 0) {
        bar.setAttribute("fill", `url(#${gradHovId})`);
        const hourLabel = `${String(i).padStart(2, "0")}:00 – ${String(i + 1).padStart(2, "0")}:00`;
        showTooltip(
          `<div class="tooltip-date">${hourLabel}</div>` +
          `<div class="tooltip-row"><span style="color:${color}">${fmtVal(val)}</span></div>`,
          0, 0   // repositioned in mousemove
        );
      }
    });

    hit.addEventListener("mousemove", e => {
      if (val > 0) positionTooltip(e.clientX, e.clientY);
    });

    hit.addEventListener("mouseleave", () => {
      if (val > 0) bar.setAttribute("fill", `url(#${gradId})`);
      hideTooltip();
    });

    svg.appendChild(hit);
  });

  // ── Fade bars in (staggered) ─────────────────────────────────────────────
  requestAnimationFrame(() => requestAnimationFrame(() => {
    bars.forEach((bar, i) => {
      if (bar._val <= 0) return;
      bar.style.transition = `opacity 0.5s ease ${i * 12}ms`;
      bar.setAttribute("opacity", "1");
    });
  }));
}

// ═══════════════════════════════════════════════════
// ── Date detail page (history click) ──
// ═══════════════════════════════════════════════════

let _currentDateDetail = null;

async function showDateDetailPage(dateStr) {
  _currentDateDetail = dateStr;
  const page = document.getElementById("page-date-detail");

  // Date title
  const d = new Date(dateStr + "T12:00:00");
  document.getElementById("date-detail-title").textContent =
    currentLang === "zh"
      ? d.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" })
      : d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

  // Show page
  page.classList.add("visible");
  page.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  page.querySelectorAll(".zh").forEach(el => { el.style.display = currentLang === "zh" ? "" : "none"; });
  page.querySelectorAll(".en").forEach(el => { el.style.display = currentLang === "en" ? "" : "none"; });

  // Placeholder while loading
  const sections = document.getElementById("date-detail-sections");
  sections.innerHTML = '<div class="dds-loading">…</div>';

  try {
    const [tokData, focData, toolData] = await Promise.all([
      fetch(`/api/hourly?metric=tokens&d=${dateStr}`).then(r => r.json()),
      fetch(`/api/hourly?metric=focus&d=${dateStr}`).then(r => r.json()),
      fetch(`/api/hourly?metric=tools&d=${dateStr}`).then(r => r.json()),
    ]);
    renderDateDetailSections(sections, [
      { data: tokData,  meta: METRIC_META.tokens },
      { data: focData,  meta: METRIC_META.focus  },
      { data: toolData, meta: METRIC_META.tools  },
    ]);
  } catch (e) {
    sections.innerHTML = '<div class="dds-loading">Failed to load</div>';
    console.error("Date detail fetch failed", e);
  }
}

function renderDateDetailSections(container, items) {
  container.innerHTML = "";
  items.forEach(({ data, meta }, idx) => {
    const pct = data.goal > 0 ? data.total / data.goal : 0;

    const section = document.createElement("div");
    section.className = "dds-section";

    // Header row
    const header = document.createElement("div");
    header.className = "dds-header";
    header.innerHTML =
      `<span class="dds-dot" style="background:${meta.color}"></span>` +
      `<span class="dds-name" style="color:${meta.color}">` +
        `<span class="zh">${meta.zhName}</span>` +
        `<span class="en">${meta.enName}</span>` +
      `</span>` +
      `<span class="dds-values">${meta.fmtVal(data.total)} / ${meta.fmtGoal(data.goal)}</span>` +
      `<span class="dds-pct" style="color:${meta.color}">${fmtPct(pct)}</span>`;
    // Apply lang
    header.querySelectorAll(".zh").forEach(el => { el.style.display = currentLang === "zh" ? "" : "none"; });
    header.querySelectorAll(".en").forEach(el => { el.style.display = currentLang === "en" ? "" : "none"; });

    // Chart
    const chartWrap = document.createElement("div");
    chartWrap.className = "dds-chart-wrap";
    const svgEl = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svgEl.setAttribute("viewBox", "0 0 510 185");
    svgEl.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svgEl.style.cssText = "width:100%;height:auto;display:block;";
    chartWrap.appendChild(svgEl);

    section.appendChild(header);
    section.appendChild(chartWrap);
    container.appendChild(section);

    renderHourlyChart(svgEl, data.hourly, meta.color, meta.fmtVal, `hbargrad-dd${idx}`);
  });
}

function hideDateDetailPage() {
  const page = document.getElementById("page-date-detail");
  page.classList.remove("visible");
  page.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  _currentDateDetail = null;
}

document.getElementById("date-detail-back").addEventListener("click", hideDateDetailPage);


// Click handlers: ring-stat rows open detail page
document.querySelectorAll(".ring-stat[data-ring]").forEach(row => {
  row.addEventListener("click", () => showDetailPage(row.dataset.ring));
});

// Back button
document.getElementById("detail-back").addEventListener("click", hideDetailPage);

// ESC to close
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if (_currentDetailMetric) hideDetailPage();
  else if (_currentDateDetail) hideDateDetailPage();
});

// ── Hash-based deep-link navigation ──────────────────────────────────────────
// menubar.py opens "http://localhost:8765/#detail=tokens" to navigate directly
// to the hourly detail page for a specific metric.

function handleHashNav() {
  const hash = window.location.hash;
  if (!hash.startsWith("#detail=")) return;
  const metric = hash.slice(8);   // "tokens" | "focus" | "tools"
  if (!METRIC_META[metric]) return;
  // Clear the hash so Back navigation doesn't re-trigger
  window.history.replaceState(null, "", window.location.pathname);
  if (_todayData) {
    showDetailPage(metric);
  } else {
    // Data not loaded yet — wait for the first refresh then open
    const tid = setInterval(() => {
      if (_todayData) {
        clearInterval(tid);
        showDetailPage(metric);
      }
    }, 100);
  }
}

window.addEventListener("hashchange", handleHashNav);
// Also check on initial page load (in case the URL already has a hash)
window.addEventListener("load", handleHashNav);
