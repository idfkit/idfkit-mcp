"""Self-contained Canvas 2D schedule heatmap viewer for the MCP Apps extension."""

from __future__ import annotations

SCHEDULE_VIEWER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>idfkit — Schedule Viewer</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    /* -- Viewport -- */
    --void: #0a0e14;

    /* -- Dusk-to-dawn palette -- */
    --dormant:  #0f1a2e;
    --setback:  #3a4556;
    --active:   #d4a054;
    --daylight: #e8dfd0;

    /* -- UI chrome (shared with geometry viewer) -- */
    --chrome-bg:     rgba(20, 20, 22, 0.85);
    --chrome-border: rgba(255, 255, 255, 0.08);
    --chrome-hover:  rgba(255, 255, 255, 0.06);
    --text-primary:  rgba(255, 255, 255, 0.88);
    --text-secondary: rgba(255, 255, 255, 0.50);
    --text-muted:    rgba(255, 255, 255, 0.30);
    --accent:        #d4a054;
    --accent-dim:    rgba(212, 160, 84, 0.25);
  }

  html, body { width: 100%; height: 100%; overflow: hidden; background: var(--void); }

  #heatmap { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }

  /* -- Time strip (persistent readout) -- */
  .time-strip {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--chrome-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--chrome-border);
    font-family: 'SF Mono', 'Cascadia Code', 'JetBrains Mono', monospace;
    font-size: 12px;
    color: var(--text-muted);
    z-index: 10;
    pointer-events: none;
    transition: color 0.15s;
  }
  .time-strip.active { color: var(--text-primary); }

  .time-strip .ts-schedule {
    color: var(--accent);
    margin-right: 12px;
    font-weight: 600;
  }
  .time-strip .ts-day { color: var(--text-secondary); margin-right: 8px; }
  .time-strip .ts-hour { color: var(--text-secondary); margin-right: 12px; }
  .time-strip .ts-value { color: var(--text-primary); font-weight: 600; }

  /* -- Floating toolbar -- */
  .toolbar {
    position: absolute;
    top: 44px;
    left: 12px;
    display: flex;
    gap: 2px;
    background: var(--chrome-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--chrome-border);
    border-radius: 6px;
    padding: 3px;
    z-index: 10;
  }

  .toolbar button {
    font-family: 'SF Mono', 'Cascadia Code', 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-secondary);
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 5px 10px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
    white-space: nowrap;
  }
  .toolbar button:hover { background: var(--chrome-hover); color: var(--text-primary); }
  .toolbar button.active { background: var(--accent-dim); color: var(--accent); }

  .toolbar .sep {
    width: 1px;
    background: var(--chrome-border);
    margin: 4px 2px;
  }

  /* -- Schedule selector dropdown -- */
  .schedule-selector {
    position: absolute;
    top: 82px;
    left: 12px;
    background: var(--chrome-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--chrome-border);
    border-radius: 6px;
    padding: 3px;
    z-index: 10;
    display: none;
    max-height: 300px;
    overflow-y: auto;
    min-width: 180px;
  }
  .schedule-selector.visible { display: block; }

  .schedule-selector button {
    display: block;
    width: 100%;
    text-align: left;
    font-family: 'SF Mono', 'Cascadia Code', 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-secondary);
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 5px 10px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 260px;
  }
  .schedule-selector button:hover { background: var(--chrome-hover); color: var(--text-primary); }
  .schedule-selector button.active { color: var(--accent); }

  /* -- Color scale legend -- */
  .color-scale {
    position: absolute;
    bottom: 12px;
    left: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--chrome-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--chrome-border);
    border-radius: 6px;
    padding: 6px 10px;
    z-index: 10;
    font-family: 'SF Mono', 'Cascadia Code', 'JetBrains Mono', monospace;
    font-size: 10px;
    color: var(--text-muted);
  }

  .color-scale .gradient-bar {
    width: 120px;
    height: 10px;
    border-radius: 3px;
    border: 1px solid var(--chrome-border);
  }

  /* -- Stats badge -- */
  .stats {
    position: absolute;
    bottom: 12px;
    right: 12px;
    font-family: 'SF Mono', 'Cascadia Code', 'JetBrains Mono', monospace;
    font-size: 10px;
    color: var(--text-muted);
    z-index: 10;
  }
</style>
</head>
<body>

<canvas id="heatmap"></canvas>

<!-- Time strip (persistent readout) -->
<div class="time-strip" id="time-strip">
  <span class="ts-schedule" id="ts-schedule"></span>
  <span class="ts-day" id="ts-day"></span>
  <span class="ts-hour" id="ts-hour"></span>
  <span class="ts-value" id="ts-value"></span>
</div>

<!-- Toolbar -->
<div class="toolbar">
  <button id="btn-week" class="active">Week</button>
  <button id="btn-year">Year</button>
  <div class="sep"></div>
  <button id="btn-schedules">Schedules</button>
</div>

<!-- Schedule selector -->
<div class="schedule-selector" id="schedule-selector"></div>

<!-- Color scale -->
<div class="color-scale" id="color-scale">
  <span id="scale-min">0</span>
  <div class="gradient-bar" id="gradient-bar"></div>
  <span id="scale-max">1</span>
</div>

<!-- Stats -->
<div class="stats" id="stats"></div>

<script type="importmap">
{
  "imports": {
    "@modelcontextprotocol/ext-apps": "https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps"
  }
}
</script>

<script type="module">
import { App } from '@modelcontextprotocol/ext-apps';

// ── State ───────────────────────────────────────────────────────────

let modelData = null;
let activeScheduleIndex = 0;
let viewMode = 'week'; // week | year
const canvas = document.getElementById('heatmap');
const ctx = canvas.getContext('2d');

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const DAY_ABBR = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

// ── Color interpolation ─────────────────────────────────────────────

// Dormant (deep blue) → Active (warm amber)
const COLOR_DORMANT = { r: 15, g: 26, b: 46 };   // #0f1a2e
const COLOR_ACTIVE  = { r: 212, g: 160, b: 84 };  // #d4a054

function valueToColor(value, min, max) {
  const t = max > min ? (value - min) / (max - min) : 0;
  const r = Math.round(COLOR_DORMANT.r + t * (COLOR_ACTIVE.r - COLOR_DORMANT.r));
  const g = Math.round(COLOR_DORMANT.g + t * (COLOR_ACTIVE.g - COLOR_DORMANT.g));
  const b = Math.round(COLOR_DORMANT.b + t * (COLOR_ACTIVE.b - COLOR_DORMANT.b));
  return `rgb(${r},${g},${b})`;
}

// ── Layout constants ────────────────────────────────────────────────

const STRIP_H = 32;     // time strip height
const LABEL_W = 48;     // y-axis label width
const LABEL_H = 20;     // x-axis label height
const PAD = 12;          // margin around heatmap

// ── Data reshaping ──────────────────────────────────────────────────

function getSchedule() {
  if (!modelData || !modelData.schedules.length) return null;
  return modelData.schedules[activeScheduleIndex];
}

function getWeekData(schedule) {
  // Average hourly values across all weeks for each day-of-week.
  // Returns 7 rows (Mon-Sun) x 24 cols (hours).
  const vals = schedule.values;
  const startDow = modelData.startDayOfWeek; // 0=Monday
  const grid = Array.from({ length: 7 }, () => ({ sum: new Float64Array(24), count: new Uint16Array(24) }));

  for (let h = 0; h < vals.length; h++) {
    const dayOfYear = Math.floor(h / 24);
    const hour = h % 24;
    const dow = (startDow + dayOfYear) % 7;
    grid[dow].sum[hour] += vals[h];
    grid[dow].count[hour]++;
  }

  return grid.map(row =>
    Array.from({ length: 24 }, (_, i) => row.count[i] > 0 ? row.sum[i] / row.count[i] : 0)
  );
}

function getYearData(schedule) {
  // Returns array of 365/366 rows, each with 24 hourly values.
  const vals = schedule.values;
  const numDays = Math.ceil(vals.length / 24);
  const rows = [];
  for (let d = 0; d < numDays; d++) {
    const row = [];
    for (let h = 0; h < 24; h++) {
      const idx = d * 24 + h;
      row.push(idx < vals.length ? vals[idx] : 0);
    }
    rows.push(row);
  }
  return rows;
}

function getValueRange(schedule) {
  const tl = schedule.typeLimits;
  if (tl && tl.lower != null && tl.upper != null) return { min: tl.lower, max: tl.upper };
  let min = Infinity, max = -Infinity;
  for (const v of schedule.values) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (min === max) { min = 0; max = max || 1; }
  return { min, max };
}

// ── Rendering ───────────────────────────────────────────────────────

// Axes: Y = hours (24 rows, 00 at bottom, 23 at top), X = days/day-of-week.
// Data is [day][hour], drawn at position (col=day, row=flipped hour).
let heatmapRect = { x: 0, y: 0, w: 0, h: 0, numDays: 0, numHours: 24 };

function render() {
  const schedule = getSchedule();
  if (!schedule) return;

  const dpr = Math.min(window.devicePixelRatio, 2);
  const W = window.innerWidth;
  const H = window.innerHeight;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  // Clear
  ctx.fillStyle = '#0a0e14';
  ctx.fillRect(0, 0, W, H);

  const { min, max } = getValueRange(schedule);
  const data = viewMode === 'week' ? getWeekData(schedule) : getYearData(schedule);
  const numDays = data.length;    // columns (x-axis)
  const numHours = 24;            // rows (y-axis)

  // Compute heatmap area
  const x0 = PAD + LABEL_W;
  const y0 = STRIP_H + PAD;
  const x1 = W - PAD;
  const y1 = H - PAD - LABEL_H;
  const cellW = (x1 - x0) / numDays;
  const cellH = (y1 - y0) / numHours;

  heatmapRect = { x: x0, y: y0, w: x1 - x0, h: y1 - y0, numDays, numHours };

  // Draw cells: col = day, row = hour (Y-axis flipped: hour 0 at bottom)
  for (let day = 0; day < numDays; day++) {
    for (let hour = 0; hour < numHours; hour++) {
      const val = data[day][hour];
      ctx.fillStyle = valueToColor(val, min, max);
      ctx.fillRect(x0 + day * cellW, y1 - (hour + 1) * cellH, cellW + 0.5, cellH + 0.5);
    }
  }

  // Day/column separators (whisper-thin)
  ctx.strokeStyle = 'rgba(255,255,255,0.04)';
  ctx.lineWidth = 0.5;
  for (let day = 1; day < numDays; day++) {
    // In year view, draw stronger lines at month boundaries
    if (viewMode === 'year') {
      let dayCount = 0;
      let isMonthBoundary = false;
      const isLeap = modelData.year % 4 === 0 && (modelData.year % 100 !== 0 || modelData.year % 400 === 0);
      const mDays = [...MONTH_DAYS];
      if (isLeap) mDays[1] = 29;
      for (let m = 0; m < 12; m++) {
        dayCount += mDays[m];
        if (day === dayCount) { isMonthBoundary = true; break; }
      }
      ctx.strokeStyle = isMonthBoundary ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.03)';
    }
    const x = x0 + day * cellW;
    ctx.beginPath();
    ctx.moveTo(x, y0);
    ctx.lineTo(x, y1);
    ctx.stroke();
  }

  // Hour/row separators (slightly stronger)
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.lineWidth = 0.5;
  for (let hour = 1; hour < numHours; hour++) {
    const y = y1 - hour * cellH;
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1, y);
    ctx.stroke();
  }

  // Outer border
  ctx.strokeStyle = 'rgba(255,255,255,0.1)';
  ctx.lineWidth = 1;
  ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);

  // Y-axis labels (hours)
  ctx.fillStyle = 'rgba(255,255,255,0.3)';
  ctx.font = '10px "SF Mono", "Cascadia Code", "JetBrains Mono", monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  const hourStep = cellH < 14 ? 3 : cellH < 22 ? 2 : 1;
  for (let hour = 0; hour < numHours; hour += hourStep) {
    ctx.fillText(String(hour).padStart(2, '0'), x0 - 6, y1 - (hour + 1) * cellH + cellH / 2);
  }

  // X-axis labels (days or months)
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  if (viewMode === 'week') {
    for (let day = 0; day < 7; day++) {
      ctx.fillText(DAY_ABBR[day], x0 + day * cellW + cellW / 2, y1 + 4);
    }
  } else {
    // Month labels at midpoints
    let dayCount = 0;
    const isLeap = modelData.year % 4 === 0 && (modelData.year % 100 !== 0 || modelData.year % 400 === 0);
    const mDays = [...MONTH_DAYS];
    if (isLeap) mDays[1] = 29;
    for (let m = 0; m < 12; m++) {
      const midDay = dayCount + Math.floor(mDays[m] / 2);
      if (midDay < numDays) {
        ctx.fillText(MONTH_NAMES[m], x0 + midDay * cellW + cellW / 2, y1 + 4);
      }
      dayCount += mDays[m];
    }
  }

  // Update color scale
  updateColorScale(min, max);
  updateStats(schedule);
}

function updateColorScale(min, max) {
  const bar = document.getElementById('gradient-bar');
  bar.style.background = `linear-gradient(to right, #0f1a2e, #d4a054)`;
  document.getElementById('scale-min').textContent = min.toFixed(1);
  document.getElementById('scale-max').textContent = max.toFixed(1);
}

function updateStats(schedule) {
  const tl = schedule.typeLimits;
  const unit = tl ? tl.unitType : '';
  document.getElementById('stats').textContent =
    `${schedule.name} · ${schedule.objectType.replace('Schedule:', '')}` +
    (unit && unit !== 'Dimensionless' ? ` · ${unit}` : '');
}

// ── Interaction ─────────────────────────────────────────────────────

function onPointerMove(event) {
  const schedule = getSchedule();
  if (!schedule) return;

  const rect = canvas.getBoundingClientRect();
  const mx = event.clientX - rect.left;
  const my = event.clientY - rect.top;

  const { x, y, w, h, numDays, numHours } = heatmapRect;
  const cellW = w / numDays;
  const cellH = h / numHours;

  const day = Math.floor((mx - x) / cellW);            // column = day
  const hour = Math.floor((y + h - my) / cellH);       // row = hour (flipped: bottom=0)

  const strip = document.getElementById('time-strip');

  if (day < 0 || day >= numDays || hour < 0 || hour >= numHours) {
    strip.classList.remove('active');
    document.getElementById('ts-schedule').textContent = '';
    document.getElementById('ts-day').textContent = '';
    document.getElementById('ts-hour').textContent = '';
    document.getElementById('ts-value').textContent = '';
    return;
  }

  strip.classList.add('active');

  const data = viewMode === 'week' ? getWeekData(schedule) : getYearData(schedule);
  const value = data[day][hour];
  const hourStr = `${String(hour).padStart(2, '0')}:00`;

  document.getElementById('ts-schedule').textContent = schedule.name;

  if (viewMode === 'week') {
    document.getElementById('ts-day').textContent = DAY_NAMES[day];
  } else {
    // Compute date from day-of-year
    const isLeap = modelData.year % 4 === 0 && (modelData.year % 100 !== 0 || modelData.year % 400 === 0);
    const mDays = [...MONTH_DAYS];
    if (isLeap) mDays[1] = 29;
    let dayCount = 0;
    let month = 0;
    for (let m = 0; m < 12; m++) {
      if (day < dayCount + mDays[m]) {
        month = m;
        break;
      }
      dayCount += mDays[m];
    }
    const dayOfMonth = day - dayCount + 1;
    const dow = (modelData.startDayOfWeek + day) % 7;
    document.getElementById('ts-day').textContent =
      `${DAY_ABBR[dow]} ${dayOfMonth} ${MONTH_NAMES[month]}`;
  }

  document.getElementById('ts-hour').textContent = hourStr;
  document.getElementById('ts-value').textContent = value.toFixed(2);

  // Highlight cell
  render();
  const dpr = Math.min(window.devicePixelRatio, 2);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.strokeStyle = 'rgba(255,255,255,0.5)';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(x + day * cellW + 0.5, y + h - (hour + 1) * cellH + 0.5, cellW - 1, cellH - 1);
}

canvas.addEventListener('pointermove', onPointerMove);

// ── View mode toggle ────────────────────────────────────────────────

function setViewMode(mode) {
  viewMode = mode;
  document.getElementById('btn-week').classList.toggle('active', mode === 'week');
  document.getElementById('btn-year').classList.toggle('active', mode === 'year');
  render();
}

document.getElementById('btn-week').addEventListener('click', () => setViewMode('week'));
document.getElementById('btn-year').addEventListener('click', () => setViewMode('year'));

// ── Schedule selector ───────────────────────────────────────────────

function buildScheduleSelector() {
  const container = document.getElementById('schedule-selector');
  container.innerHTML = '';
  if (!modelData) return;

  modelData.schedules.forEach((schedule, i) => {
    const btn = document.createElement('button');
    btn.textContent = schedule.name || '(unnamed)';
    btn.dataset.index = String(i);
    if (i === activeScheduleIndex) btn.classList.add('active');
    btn.addEventListener('click', () => selectSchedule(i));
    container.appendChild(btn);
  });

  // Only show the Schedules button if there are multiple
  const btnSchedules = document.getElementById('btn-schedules');
  btnSchedules.style.display = modelData.schedules.length > 1 ? '' : 'none';
  // Also hide the separator before it
  const sep = btnSchedules.previousElementSibling;
  if (sep && sep.classList.contains('sep')) {
    sep.style.display = modelData.schedules.length > 1 ? '' : 'none';
  }
}

function selectSchedule(index) {
  activeScheduleIndex = index;
  const container = document.getElementById('schedule-selector');
  container.querySelectorAll('button').forEach(b => {
    b.classList.toggle('active', b.dataset.index === String(index));
  });
  render();
}

function toggleScheduleSelector() {
  const el = document.getElementById('schedule-selector');
  const btn = document.getElementById('btn-schedules');
  const visible = el.classList.toggle('visible');
  btn.classList.toggle('active', visible);
}

document.getElementById('btn-schedules').addEventListener('click', toggleScheduleSelector);

// ── Resize ──────────────────────────────────────────────────────────

window.addEventListener('resize', () => { if (modelData) render(); });

// ── Model loading ───────────────────────────────────────────────────

function loadModel(data) {
  modelData = data;
  activeScheduleIndex = 0;
  buildScheduleSelector();
  render();
}

// ── MCP Apps integration ────────────────────────────────────────────

function handleToolResult({ content }) {
  const textItem = content?.find(c => c.type === 'text');
  if (!textItem) return;
  try {
    const data = JSON.parse(textItem.text);
    if (data.schedules) loadModel(data);
  } catch (e) {
    console.debug('[idfkit-schedule-viewer] Could not parse tool result', e);
  }
}

const app = new App({ name: 'idfkit Schedule Viewer', version: '1.0.0' });
app.ontoolresult = handleToolResult;
await app.connect();

// Standalone testing fallback.
if (window.__IDFKIT_DATA__) {
  loadModel(window.__IDFKIT_DATA__);
}
</script>
</body>
</html>
"""
