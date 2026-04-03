"""Self-contained Canvas 2D peak-load viewer HTML for the MCP Apps extension."""

from __future__ import annotations

PEAK_LOADS_VIEWER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>idfkit — Peak Load Viewer</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --void: #081018;
    --panel: rgba(12, 18, 27, 0.88);
    --panel-border: rgba(255, 255, 255, 0.08);
    --panel-hover: rgba(255, 255, 255, 0.04);
    --text-primary: rgba(255, 255, 255, 0.90);
    --text-secondary: rgba(255, 255, 255, 0.62);
    --text-muted: rgba(255, 255, 255, 0.36);
    --grid: rgba(255, 255, 255, 0.08);
    --track: rgba(255, 255, 255, 0.08);
    --mode-accent: #63d0c5;
    --mode-accent-dim: rgba(99, 208, 197, 0.22);
    --mode-positive: #63d0c5;
    --mode-negative: #4f7297;
    --mode-total: #efbe5b;
    --warning: #efbe5b;
    --danger: #f07167;
    --ok: #67c587;
    --info: #7eb8ff;
  }

  html, body {
    width: 100%;
    min-height: 100%;
    background:
      radial-gradient(circle at top left, rgba(99, 208, 197, 0.14), transparent 28%),
      radial-gradient(circle at bottom right, rgba(240, 138, 93, 0.12), transparent 24%),
      linear-gradient(180deg, #081018 0%, #09111a 100%);
    color: var(--text-primary);
  }

  body {
    font-family: 'SF Mono', 'Cascadia Code', 'JetBrains Mono', monospace;
    overflow: auto;
  }

  .shell {
    min-height: 100vh;
    padding: 14px;
    display: grid;
    gap: 12px;
    grid-template-rows: auto auto minmax(300px, 1.3fr) minmax(260px, 0.95fr);
  }

  .topbar {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 12px;
  }

  .eyebrow {
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 6px;
  }

  h1, h2 {
    font-weight: 600;
    letter-spacing: -0.04em;
  }

  h1 {
    font-size: 24px;
    line-height: 1.05;
  }

  h2 {
    font-size: 14px;
    line-height: 1.1;
  }

  .subtitle {
    margin-top: 8px;
    font-size: 11px;
    color: var(--text-secondary);
    max-width: 560px;
  }

  .mode-switch {
    display: flex;
    gap: 3px;
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 8px;
    padding: 3px;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
  }

  .mode-switch button {
    border: none;
    background: transparent;
    color: var(--text-secondary);
    border-radius: 6px;
    padding: 7px 14px;
    font: inherit;
    font-size: 11px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .mode-switch button:hover { background: var(--panel-hover); color: var(--text-primary); }
  .mode-switch button.active { background: var(--mode-accent-dim); color: var(--mode-accent); }

  .metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
  }

  .metric-card,
  .panel {
    background: var(--panel);
    border: 1px solid var(--panel-border);
    border-radius: 12px;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
  }

  .metric-card {
    padding: 14px;
    min-height: 96px;
  }

  .metric-label {
    font-size: 10px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 10px;
  }

  .metric-value {
    font-size: 24px;
    color: var(--text-primary);
    letter-spacing: -0.04em;
    line-height: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .metric-note {
    margin-top: 8px;
    font-size: 10px;
    color: var(--text-secondary);
    line-height: 1.4;
  }

  .main-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.45fr) minmax(290px, 0.9fr);
    gap: 12px;
    min-height: 0;
  }

  .side-column,
  .panel {
    min-height: 0;
  }

  .panel {
    padding: 14px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .panel-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 10px;
  }

  .panel-note {
    font-size: 10px;
    color: var(--text-secondary);
    text-align: right;
    line-height: 1.4;
  }

  .canvas-wrap {
    position: relative;
    flex: 1;
    min-height: 260px;
  }

  canvas {
    width: 100%;
    height: 100%;
    display: block;
  }

  .side-column {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
    gap: 12px;
  }

  .timing-stack {
    display: grid;
    gap: 10px;
  }

  .timing-meta {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    align-items: baseline;
    flex-wrap: wrap;
  }

  .timing-meta strong {
    font-size: 16px;
    color: var(--text-primary);
  }

  .timing-meta span {
    font-size: 11px;
    color: var(--text-secondary);
  }

  .timing-track {
    position: relative;
    height: 42px;
    border-radius: 10px;
    background: linear-gradient(90deg, rgba(255,255,255,0.03), rgba(255,255,255,0.08), rgba(255,255,255,0.03));
    border: 1px solid var(--panel-border);
    overflow: hidden;
  }

  .timing-band {
    position: absolute;
    top: 0;
    bottom: 0;
    border-radius: 8px;
  }

  .timing-marker {
    position: absolute;
    top: 3px;
    bottom: 3px;
    width: 2px;
    background: var(--text-primary);
    border-radius: 999px;
    box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.08);
  }

  .timing-marker::after {
    content: "";
    position: absolute;
    left: 50%;
    top: -4px;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--text-primary);
    transform: translateX(-50%);
  }

  .timing-hours {
    display: flex;
    justify-content: space-between;
    font-size: 10px;
    color: var(--text-muted);
  }

  .flags-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-content: flex-start;
    overflow: auto;
    padding-right: 2px;
  }

  .flag-badge {
    border-radius: 999px;
    padding: 7px 11px;
    font-size: 10px;
    line-height: 1.4;
    border: 1px solid transparent;
    color: var(--text-primary);
  }

  .flag-badge.warning {
    background: rgba(239, 190, 91, 0.14);
    border-color: rgba(239, 190, 91, 0.28);
  }

  .flag-badge.danger {
    background: rgba(240, 113, 103, 0.14);
    border-color: rgba(240, 113, 103, 0.28);
  }

  .flag-badge.info {
    background: rgba(126, 184, 255, 0.14);
    border-color: rgba(126, 184, 255, 0.28);
  }

  .flag-badge.ok {
    background: rgba(103, 197, 135, 0.14);
    border-color: rgba(103, 197, 135, 0.28);
  }

  .bottom-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
    gap: 12px;
    min-height: 0;
  }

  .component-list {
    display: grid;
    gap: 10px;
    overflow: auto;
    padding-right: 2px;
  }

  .component-row {
    display: grid;
    gap: 6px;
  }

  .component-head {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    align-items: baseline;
    font-size: 11px;
    color: var(--text-primary);
  }

  .component-meta {
    font-size: 10px;
    color: var(--text-secondary);
  }

  .component-bar {
    height: 7px;
    border-radius: 999px;
    background: var(--track);
    overflow: hidden;
  }

  .component-bar-fill {
    display: block;
    height: 100%;
    border-radius: inherit;
  }

  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-muted);
    font-size: 12px;
    text-align: center;
    padding: 24px;
  }

  @media (max-width: 1100px) {
    .shell {
      grid-template-rows: auto auto minmax(340px, auto) minmax(420px, auto);
    }

    .metrics,
    .main-grid,
    .bottom-grid {
      grid-template-columns: 1fr;
    }

    .side-column {
      grid-template-rows: auto auto;
    }
  }

  @media (max-width: 720px) {
    .shell { padding: 10px; gap: 10px; }
    .topbar { flex-direction: column; align-items: stretch; }
    .metrics { grid-template-columns: 1fr 1fr; }
  }
</style>
</head>
<body>
<div class="shell">
  <div class="topbar">
    <div>
      <div class="eyebrow">Peak Load QA/QC</div>
      <h1 id="title">Facility cooling peak</h1>
      <div class="subtitle" id="subtitle">Peak-load decomposition with timing checks, zone intensity ranking, and QA flags.</div>
    </div>
    <div class="mode-switch">
      <button id="btn-cooling" class="active">Cooling</button>
      <button id="btn-heating">Heating</button>
    </div>
  </div>

  <div class="metrics">
    <div class="metric-card">
      <div class="metric-label">Peak Magnitude</div>
      <div class="metric-value" id="metric-peak">N/A</div>
      <div class="metric-note" id="metric-peak-note"></div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Peak Intensity</div>
      <div class="metric-value" id="metric-density">N/A</div>
      <div class="metric-note" id="metric-density-note"></div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Top Zone</div>
      <div class="metric-value" id="metric-zone">N/A</div>
      <div class="metric-note" id="metric-zone-note"></div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Design-Day Sizing</div>
      <div class="metric-value" id="metric-sizing">N/A</div>
      <div class="metric-note" id="metric-sizing-note"></div>
    </div>
  </div>

  <div class="main-grid">
    <section class="panel">
      <div class="panel-header">
        <div>
          <div class="eyebrow">Waterfall</div>
          <h2>Signed component balance at peak timestamp</h2>
        </div>
        <div class="panel-note" id="waterfall-note"></div>
      </div>
      <div class="canvas-wrap">
        <canvas id="waterfall"></canvas>
      </div>
    </section>

    <div class="side-column">
      <section class="panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">Timing</div>
            <h2>Peak timing indicator</h2>
          </div>
          <div class="panel-note" id="timing-expected"></div>
        </div>
        <div class="timing-stack">
          <div class="timing-meta">
            <strong id="timing-value">N/A</strong>
            <span id="timing-stamp"></span>
          </div>
          <div class="timing-track" id="timing-track"></div>
          <div class="timing-hours">
            <span>00</span>
            <span>06</span>
            <span>12</span>
            <span>18</span>
            <span>24</span>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">QA Flags</div>
            <h2 id="flags-title">Generated checks</h2>
          </div>
          <div class="panel-note" id="flags-note"></div>
        </div>
        <div class="flags-list" id="flags-list"></div>
      </section>
    </div>
  </div>

  <div class="bottom-grid">
    <section class="panel">
      <div class="panel-header">
        <div>
          <div class="eyebrow">Zones</div>
          <h2>Top zones by load intensity</h2>
        </div>
        <div class="panel-note" id="zones-note"></div>
      </div>
      <div class="canvas-wrap">
        <canvas id="zones"></canvas>
      </div>
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <div class="eyebrow">Components</div>
          <h2>Largest contributors</h2>
        </div>
        <div class="panel-note" id="components-note"></div>
      </div>
      <div class="component-list" id="component-list"></div>
    </section>
  </div>
</div>

<script type="importmap">
{
  "imports": {
    "@modelcontextprotocol/ext-apps": "https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps"
  }
}
</script>

<script type="module">
import { App } from '@modelcontextprotocol/ext-apps';

const WATERFALL_LIMIT = 8;
const ZONE_LIMIT = 10;

const MODE_META = {
  cooling: {
    label: 'Cooling',
    accent: '#63d0c5',
    accentDim: 'rgba(99, 208, 197, 0.22)',
    positive: '#63d0c5',
    negative: '#4f7297',
    total: '#efbe5b',
    expectedBands: [[12, 20]],
    expectedText: 'Expected between 12:00 and 20:00'
  },
  heating: {
    label: 'Heating',
    accent: '#f08a5d',
    accentDim: 'rgba(240, 138, 93, 0.22)',
    positive: '#f08a5d',
    negative: '#6286a8',
    total: '#efbe5b',
    expectedBands: [[0, 8], [18, 24]],
    expectedText: 'Expected near morning start-up or evening setback'
  }
};

let analysisData = null;
let activeMode = 'cooling';

const waterfallCanvas = document.getElementById('waterfall');
const waterfallCtx = waterfallCanvas.getContext('2d');
const zonesCanvas = document.getElementById('zones');
const zonesCtx = zonesCanvas.getContext('2d');

function formatNumber(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  }).format(value);
}

function formatWatts(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
  const abs = Math.abs(value);
  if (abs >= 1000) return `${formatNumber(value / 1000, 1)} kW`;
  return `${formatNumber(value, digits)} W`;
}

function formatSignedWatts(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
  return `${value >= 0 ? '+' : '-'}${formatWatts(Math.abs(value), 1)}`;
}

function formatDensity(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';
  return `${formatNumber(value, 1)} W/m²`;
}

function truncate(text, max = 20) {
  if (!text) return 'N/A';
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function parseHour(timestamp) {
  if (!timestamp) return null;
  const match = timestamp.match(/(\d{1,2}):(\d{2})/);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  return Math.max(0, Math.min(24, hour + (minute / 60)));
}

function formatHour(hour) {
  if (hour === null || hour === undefined || Number.isNaN(hour)) return 'N/A';
  const whole = Math.floor(Math.min(hour, 23.999));
  const minute = Math.round((hour - whole) * 60);
  return `${String(whole).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

function severityForFlag(text) {
  if (/very high|unit errors|significantly oversized|>2\.5x/i.test(text)) return 'danger';
  if (/oversized|design-day|design days/i.test(text)) return 'info';
  return 'warning';
}

function currentSummary() {
  return analysisData ? analysisData[activeMode] : null;
}

function currentSizing() {
  if (!analysisData) return [];
  return analysisData[`sizing_${activeMode}`] || [];
}

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function applyModeTheme() {
  const meta = MODE_META[activeMode];
  document.documentElement.style.setProperty('--mode-accent', meta.accent);
  document.documentElement.style.setProperty('--mode-accent-dim', meta.accentDim);
  document.documentElement.style.setProperty('--mode-positive', meta.positive);
  document.documentElement.style.setProperty('--mode-negative', meta.negative);
  document.documentElement.style.setProperty('--mode-total', meta.total);
  document.getElementById('btn-cooling').classList.toggle('active', activeMode === 'cooling');
  document.getElementById('btn-heating').classList.toggle('active', activeMode === 'heating');
}

function getTopZone(summary) {
  if (!summary || !summary.zones || !summary.zones.length) return null;
  const zonesWithDensity = summary.zones.filter(zone => zone.peak_w_per_m2 !== null && zone.peak_w_per_m2 !== undefined);
  if (zonesWithDensity.length) {
    return [...zonesWithDensity].sort((a, b) => b.peak_w_per_m2 - a.peak_w_per_m2)[0];
  }
  return summary.zones[0];
}

function getTopSizing() {
  const sizing = currentSizing();
  if (!sizing.length) return null;
  return [...sizing].sort((a, b) => {
    const aValue = a.user_load_w ?? a.calculated_load_w ?? 0;
    const bValue = b.user_load_w ?? b.calculated_load_w ?? 0;
    return bValue - aValue;
  })[0];
}

function computeWaterfall(summary) {
  const components = (summary?.components || []).slice(0, WATERFALL_LIMIT);
  let running = 0;
  const bars = components.map(component => {
    const start = running;
    running += Number(component.value_w || 0);
    return { ...component, start, end: running };
  });
  return { bars, signedTotal: running };
}

function renderMetrics() {
  const summary = currentSummary();
  const topZone = getTopZone(summary);
  const topSizing = getTopSizing();

  setText('title', `Facility ${MODE_META[activeMode].label.toLowerCase()} peak`);
  setText(
    'subtitle',
    analysisData
      ? `Total floor area ${formatNumber(analysisData.total_floor_area_m2, 1)} m² with ${summary?.zones?.length || 0} zone peak records.`
      : 'Peak-load decomposition with timing checks, zone intensity ranking, and QA flags.'
  );

  setText('metric-peak', summary ? formatWatts(summary.peak_w) : 'N/A');
  setText('metric-peak-note', summary?.peak_timestamp || 'Peak timestamp unavailable');

  setText('metric-density', summary ? formatDensity(summary.peak_w_per_m2) : 'N/A');
  setText(
    'metric-density-note',
    analysisData ? `${formatNumber(analysisData.total_floor_area_m2, 1)} m² total floor area` : ''
  );

  setText('metric-zone', topZone ? truncate(topZone.zone_name, 18) : 'N/A');
  setText(
    'metric-zone-note',
    topZone
      ? `${formatDensity(topZone.peak_w_per_m2)} • ${formatWatts(topZone.peak_w)}`
      : 'No zone-level peaks available'
  );

  const sizingValue = topSizing ? (topSizing.user_load_w ?? topSizing.calculated_load_w) : null;
  setText('metric-sizing', sizingValue !== null ? formatWatts(sizingValue) : 'N/A');
  setText(
    'metric-sizing-note',
    topSizing
      ? `${truncate(topSizing.zone_name, 20)}${topSizing.design_day ? ` • ${topSizing.design_day}` : ''}`
      : 'No design-day sizing records'
  );
}

function renderTiming() {
  const summary = currentSummary();
  const meta = MODE_META[activeMode];
  const timingTrack = document.getElementById('timing-track');
  timingTrack.innerHTML = '';

  setText('timing-expected', meta.expectedText);

  if (!summary) {
    setText('timing-value', 'N/A');
    setText('timing-stamp', '');
    return;
  }

  const hour = parseHour(summary.peak_timestamp);
  setText('timing-value', formatHour(hour));
  setText('timing-stamp', summary.peak_timestamp || 'Peak timestamp unavailable');

  meta.expectedBands.forEach(([start, end]) => {
    const band = document.createElement('div');
    band.className = 'timing-band';
    band.style.left = `${(start / 24) * 100}%`;
    band.style.width = `${((end - start) / 24) * 100}%`;
    band.style.background = meta.accentDim;
    timingTrack.appendChild(band);
  });

  if (hour !== null) {
    const marker = document.createElement('div');
    marker.className = 'timing-marker';
    marker.style.left = `calc(${(Math.min(hour, 24) / 24) * 100}% - 1px)`;
    timingTrack.appendChild(marker);
  }
}

function renderFlags() {
  const flags = analysisData?.flags || [];
  const list = document.getElementById('flags-list');
  list.innerHTML = '';

  setText('flags-title', flags.length ? 'Generated checks' : 'No QA concerns detected');
  setText('flags-note', `${flags.length} flag${flags.length === 1 ? '' : 's'}`);

  if (!flags.length) {
    const badge = document.createElement('div');
    badge.className = 'flag-badge ok';
    badge.textContent = 'No QA flags generated from the current thresholds.';
    list.appendChild(badge);
    return;
  }

  flags.forEach(flag => {
    const badge = document.createElement('div');
    badge.className = `flag-badge ${severityForFlag(flag)}`;
    badge.textContent = flag;
    list.appendChild(badge);
  });
}

function renderComponentList() {
  const summary = currentSummary();
  const list = document.getElementById('component-list');
  list.innerHTML = '';

  if (!summary || !summary.components?.length) {
    setText('components-note', 'No component breakdown available');
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'No component breakdown available.';
    list.appendChild(empty);
    return;
  }

  setText('components-note', `${summary.components.length} component entries`);

  [...summary.components].sort((a, b) => b.value_w - a.value_w).slice(0, 10).forEach(component => {
    const row = document.createElement('div');
    row.className = 'component-row';

    const head = document.createElement('div');
    head.className = 'component-head';

    const name = document.createElement('span');
    name.textContent = component.name;
    const value = document.createElement('span');
    value.textContent = formatSignedWatts(component.value_w);

    head.appendChild(name);
    head.appendChild(value);

    const meta = document.createElement('div');
    meta.className = 'component-meta';
    meta.textContent = component.percent !== null && component.percent !== undefined
      ? `${formatNumber(component.percent, 1)}% of absolute component magnitude`
      : 'Percent share unavailable';

    const bar = document.createElement('div');
    bar.className = 'component-bar';
    const fill = document.createElement('span');
    fill.className = 'component-bar-fill';
    fill.style.width = `${Math.max(6, Math.min(100, component.percent || 0))}%`;
    fill.style.background = component.value_w >= 0 ? MODE_META[activeMode].positive : MODE_META[activeMode].negative;
    bar.appendChild(fill);

    row.appendChild(head);
    row.appendChild(meta);
    row.appendChild(bar);
    list.appendChild(row);
  });
}

function prepareCanvas(canvas, ctx) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  return { width: rect.width, height: rect.height };
}

function drawRoundedRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, Math.abs(width) / 2, Math.abs(height) / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r);
  ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r);
  ctx.closePath();
}

function drawEmptyState(ctx, width, height, message) {
  ctx.fillStyle = 'rgba(255, 255, 255, 0.36)';
  ctx.font = '12px "SF Mono", "Cascadia Code", "JetBrains Mono", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(message, width / 2, height / 2);
}

function drawWaterfall() {
  const { width, height } = prepareCanvas(waterfallCanvas, waterfallCtx);
  const summary = currentSummary();
  const meta = MODE_META[activeMode];

  if (!summary || !summary.components?.length) {
    setText('waterfall-note', 'No component data');
    drawEmptyState(waterfallCtx, width, height, 'No component data available.');
    return;
  }

  const { bars, signedTotal } = computeWaterfall(summary);
  setText('waterfall-note', `Reported peak ${formatWatts(summary.peak_w)} • Signed balance ${formatSignedWatts(signedTotal)}`);

  const left = 76;
  const right = 22;
  const top = 24;
  const bottom = 46;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;

  const values = [0, summary.peak_w, signedTotal];
  bars.forEach(bar => values.push(bar.start, bar.end));
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const padding = Math.max(400, (rawMax - rawMin || 1000) * 0.16);
  const minValue = rawMin - padding;
  const maxValue = rawMax + padding;
  const valueRange = Math.max(1, maxValue - minValue);
  const yFor = value => top + ((maxValue - value) / valueRange) * plotHeight;

  waterfallCtx.strokeStyle = 'rgba(255, 255, 255, 0.07)';
  waterfallCtx.lineWidth = 1;
  waterfallCtx.font = '10px "SF Mono", "Cascadia Code", "JetBrains Mono", monospace';
  waterfallCtx.fillStyle = 'rgba(255, 255, 255, 0.36)';
  waterfallCtx.textAlign = 'right';
  waterfallCtx.textBaseline = 'middle';

  const gridCount = plotHeight < 180 ? 2 : 4;
  for (let i = 0; i <= gridCount; i += 1) {
    const value = minValue + (valueRange * i / gridCount);
    const y = yFor(value);
    waterfallCtx.beginPath();
    waterfallCtx.moveTo(left, y);
    waterfallCtx.lineTo(width - right, y);
    waterfallCtx.stroke();
    waterfallCtx.fillText(formatWatts(value), left - 8, y);
  }

  const zeroY = yFor(0);
  waterfallCtx.strokeStyle = 'rgba(255, 255, 255, 0.18)';
  waterfallCtx.beginPath();
  waterfallCtx.moveTo(left, zeroY);
  waterfallCtx.lineTo(width - right, zeroY);
  waterfallCtx.stroke();

  const peakY = yFor(summary.peak_w);
  waterfallCtx.save();
  waterfallCtx.setLineDash([5, 4]);
  waterfallCtx.strokeStyle = meta.total;
  waterfallCtx.beginPath();
  waterfallCtx.moveTo(left, peakY);
  waterfallCtx.lineTo(width - right, peakY);
  waterfallCtx.stroke();
  waterfallCtx.restore();

  waterfallCtx.fillStyle = meta.total;
  waterfallCtx.textAlign = 'right';
  waterfallCtx.fillText(`peak ${formatWatts(summary.peak_w)}`, width - right - 6, peakY - 8);

  const slotCount = bars.length + 1;
  const step = plotWidth / Math.max(slotCount, 1);
  const barWidth = Math.min(74, step * 0.56);
  // Estimate max label chars that fit in each slot (~6.6px per char at 10px mono)
  const maxLabelChars = Math.max(4, Math.floor(step / 6.6));
  const rotateLabels = step < 60;

  waterfallCtx.textAlign = 'center';
  waterfallCtx.textBaseline = 'alphabetic';

  bars.forEach((bar, index) => {
    const centerX = left + step * (index + 0.5);
    const x = centerX - (barWidth / 2);
    const y1 = yFor(bar.start);
    const y2 = yFor(bar.end);
    const rectY = Math.min(y1, y2);
    const rectH = Math.max(2, Math.abs(y2 - y1));

    if (index > 0) {
      const previousCenter = left + step * (index - 0.5);
      waterfallCtx.strokeStyle = 'rgba(255, 255, 255, 0.18)';
      waterfallCtx.beginPath();
      waterfallCtx.moveTo(previousCenter + (barWidth / 2), y1);
      waterfallCtx.lineTo(x, y1);
      waterfallCtx.stroke();
    } else {
      waterfallCtx.strokeStyle = 'rgba(255, 255, 255, 0.18)';
      waterfallCtx.beginPath();
      waterfallCtx.moveTo(left, y1);
      waterfallCtx.lineTo(x, y1);
      waterfallCtx.stroke();
    }

    drawRoundedRect(waterfallCtx, x, rectY, barWidth, rectH, 6);
    waterfallCtx.fillStyle = bar.value_w >= 0 ? meta.positive : meta.negative;
    waterfallCtx.fill();

    waterfallCtx.fillStyle = 'rgba(255, 255, 255, 0.86)';
    waterfallCtx.font = '10px "SF Mono", "Cascadia Code", "JetBrains Mono", monospace';
    waterfallCtx.fillText(formatSignedWatts(bar.value_w), centerX, rectY - 6);

    waterfallCtx.fillStyle = 'rgba(255, 255, 255, 0.56)';
    const label = truncate(bar.name, maxLabelChars);
    if (rotateLabels) {
      waterfallCtx.save();
      waterfallCtx.translate(centerX, height - bottom + 10);
      waterfallCtx.rotate(-Math.PI / 4);
      waterfallCtx.textAlign = 'right';
      waterfallCtx.fillText(label, 0, 0);
      waterfallCtx.restore();
    } else {
      waterfallCtx.fillText(label, centerX, height - bottom + 16);
    }
  });

  const totalCenter = left + step * (bars.length + 0.5);
  const totalX = totalCenter - (barWidth / 2);
  const totalY = yFor(signedTotal);
  const totalHeight = Math.abs(zeroY - totalY);
  drawRoundedRect(waterfallCtx, totalX, Math.min(totalY, zeroY), barWidth, Math.max(2, totalHeight), 6);
  waterfallCtx.fillStyle = meta.total;
  waterfallCtx.fill();
  waterfallCtx.fillStyle = 'rgba(255, 255, 255, 0.90)';
  waterfallCtx.fillText(formatSignedWatts(signedTotal), totalCenter, Math.min(totalY, zeroY) - 6);
  waterfallCtx.fillStyle = 'rgba(255, 255, 255, 0.56)';
  if (rotateLabels) {
    waterfallCtx.save();
    waterfallCtx.translate(totalCenter, height - bottom + 10);
    waterfallCtx.rotate(-Math.PI / 4);
    waterfallCtx.textAlign = 'right';
    waterfallCtx.fillText('Net', 0, 0);
    waterfallCtx.restore();
  } else {
    waterfallCtx.fillText('Net', totalCenter, height - bottom + 16);
  }
}

function drawZones() {
  const { width, height } = prepareCanvas(zonesCanvas, zonesCtx);
  const summary = currentSummary();
  const meta = MODE_META[activeMode];

  if (!summary || !summary.zones?.length) {
    setText('zones-note', 'No zone peaks available');
    drawEmptyState(zonesCtx, width, height, 'No zone-level peak data available.');
    return;
  }

  const densityZones = summary.zones.filter(zone => zone.peak_w_per_m2 !== null && zone.peak_w_per_m2 !== undefined);
  const ranked = (densityZones.length ? densityZones : summary.zones)
    .slice()
    .sort((a, b) => {
      const aValue = densityZones.length ? a.peak_w_per_m2 : a.peak_w;
      const bValue = densityZones.length ? b.peak_w_per_m2 : b.peak_w;
      return (bValue || 0) - (aValue || 0);
    })
    .slice(0, ZONE_LIMIT);

  setText('zones-note', densityZones.length ? 'Ranked by W/m²' : 'Ranked by total W');

  zonesCtx.font = '11px "SF Mono", "Cascadia Code", "JetBrains Mono", monospace';
  zonesCtx.textBaseline = 'middle';

  // Measure the widest zone name and value label to set dynamic margins
  const maxNameChars = Math.min(24, Math.floor((width * 0.35) / 7));
  const nameLabels = ranked.map(z => truncate(z.zone_name, maxNameChars));
  const valueLabels = ranked.map(z => {
    const v = densityZones.length ? (z.peak_w_per_m2 || 0) : z.peak_w;
    return densityZones.length ? formatDensity(v) : formatWatts(v);
  });
  const maxNameWidth = Math.max(...nameLabels.map(l => zonesCtx.measureText(l).width), 40);
  const maxValueWidth = Math.max(...valueLabels.map(l => zonesCtx.measureText(l).width), 40);
  const left = Math.ceil(maxNameWidth + 14);
  const right = Math.ceil(maxValueWidth + 14);
  const top = 18;
  const bottom = 20;
  const plotWidth = Math.max(40, width - left - right);
  const rowHeight = Math.max(24, (height - top - bottom) / Math.max(ranked.length, 1));
  const barHeight = Math.min(16, rowHeight * 0.46);
  const maxValue = Math.max(...ranked.map(zone => densityZones.length ? (zone.peak_w_per_m2 || 0) : zone.peak_w), 1);

  ranked.forEach((zone, index) => {
    const value = densityZones.length ? (zone.peak_w_per_m2 || 0) : zone.peak_w;
    const y = top + (rowHeight * index) + (rowHeight / 2);
    const barWidth = plotWidth * (value / maxValue);

    zonesCtx.fillStyle = 'rgba(255, 255, 255, 0.56)';
    zonesCtx.textAlign = 'right';
    zonesCtx.fillText(nameLabels[index], left - 10, y);

    zonesCtx.fillStyle = 'rgba(255, 255, 255, 0.10)';
    drawRoundedRect(zonesCtx, left, y - (barHeight / 2), plotWidth, barHeight, 6);
    zonesCtx.fill();

    zonesCtx.fillStyle = meta.accent;
    drawRoundedRect(zonesCtx, left, y - (barHeight / 2), Math.max(2, barWidth), barHeight, 6);
    zonesCtx.fill();

    zonesCtx.fillStyle = 'rgba(255, 255, 255, 0.86)';
    zonesCtx.textAlign = 'left';
    zonesCtx.fillText(valueLabels[index], width - right + 10, y);
  });
}

function render() {
  applyModeTheme();
  renderMetrics();
  renderTiming();
  renderFlags();
  renderComponentList();
  drawWaterfall();
  drawZones();
}

function loadModel(data) {
  analysisData = data;
  activeMode = 'cooling';
  render();
}

document.getElementById('btn-cooling').addEventListener('click', () => {
  activeMode = 'cooling';
  if (analysisData) render();
});

document.getElementById('btn-heating').addEventListener('click', () => {
  activeMode = 'heating';
  if (analysisData) render();
});

window.addEventListener('resize', () => {
  if (analysisData) render();
});

function handleToolResult(result) {
  if (result?.structuredContent?.cooling && result?.structuredContent?.heating) {
    loadModel(result.structuredContent);
    return;
  }

  const textItem = result?.content?.find(item => item.type === 'text');
  if (!textItem) return;
  try {
    const data = JSON.parse(textItem.text);
    if (data.cooling && data.heating) loadModel(data);
  } catch (error) {
    console.debug('[idfkit-peak-loads-viewer] Could not parse tool result', error);
  }
}

const app = new App({ name: 'idfkit Peak Load Viewer', version: '1.0.0' });
app.ontoolresult = handleToolResult;
await app.connect();

if (window.__IDFKIT_DATA__) {
  loadModel(window.__IDFKIT_DATA__);
}
</script>
</body>
</html>
"""
