"""Self-contained report viewer HTML for the MCP Apps extension."""

from __future__ import annotations

REPORT_VIEWER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EnergyPlus Report Viewer</title>
<script type="importmap">
{ "imports": { "@modelcontextprotocol/ext-apps": "https://unpkg.com/@modelcontextprotocol/ext-apps@1.0.1/app-with-deps" } }
</script>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #10141a; --rail: #13181f; --thead: #181e28;
  --row-alt: rgba(255,255,255,0.02); --text: rgba(255,255,255,0.88);
  --text2: rgba(255,255,255,0.55); --muted: rgba(255,255,255,0.32);
  --accent: #5b9bd5; --accent-dim: rgba(91,155,213,0.15);
  --border: rgba(255,255,255,0.07); --hl: rgba(91,155,213,0.3);
  --font: 'SF Mono','Cascadia Code','JetBrains Mono','Fira Code',monospace;
  --rail-w: 260px;
}
html, body { height: 100%; background: var(--bg); color: var(--text); font: 10.5px/1.5 var(--font); }
a { color: var(--accent); text-decoration: none; }

/* layout */
#app { display: flex; height: 100%; overflow: hidden; }
#rail {
  width: var(--rail-w); min-width: var(--rail-w); background: var(--rail);
  border-right: 1px solid var(--border); display: flex; flex-direction: column;
  transition: transform 0.2s ease; z-index: 10;
}
#rail.collapsed { transform: translateX(calc(-1 * var(--rail-w))); margin-right: calc(-1 * var(--rail-w)); }
#main { flex: 1; overflow-y: auto; padding: 16px 28px 60px; }
#topbar {
  display: flex; gap: 16px; align-items: baseline; padding: 10px 28px;
  border-bottom: 1px solid var(--border); color: var(--text2); font-size: 10px;
  flex-shrink: 0;
}
#topbar .building { color: var(--text); font-size: 11px; font-weight: 600; }
#hamburger {
  display: none; position: fixed; top: 8px; left: 8px; z-index: 20;
  background: var(--rail); border: 1px solid var(--border); color: var(--text);
  font-size: 16px; width: 32px; height: 32px; cursor: pointer; border-radius: 4px;
}

/* search */
#search-wrap {
  padding: 10px; border-bottom: 1px solid var(--border); position: relative;
}
#search-wrap::before {
  content: '\26B2'; position: absolute; left: 18px; top: 50%; transform: translateY(-50%) rotate(45deg);
  color: var(--muted); font-size: 12px; pointer-events: none;
}
#search {
  width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
  color: var(--text); font: 10px var(--font); padding: 5px 8px 5px 26px; outline: none;
}
#search:focus { border-color: var(--accent); }

/* rail index */
#index { flex: 1; overflow-y: auto; padding: 6px 0; }
.rpt-group { border-bottom: 1px solid var(--border); }
.rpt-toggle {
  display: block; width: 100%; background: none; border: none; color: var(--text2);
  font: 10px var(--font); text-align: left; padding: 5px 10px; cursor: pointer;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.rpt-toggle:hover { color: var(--text); background: var(--accent-dim); }
.rpt-toggle::before { content: '\25B8'; margin-right: 6px; font-size: 8px; display: inline-block; transition: transform 0.15s; }
.rpt-group.open > .rpt-toggle::before { transform: rotate(90deg); }
.rpt-tables { display: none; }
.rpt-group.open > .rpt-tables { display: block; }
.tbl-link {
  display: block; padding: 3px 10px 3px 24px; color: var(--muted); cursor: pointer;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 10px;
}
.tbl-link:hover { color: var(--text2); }
.tbl-link.active { color: var(--accent); background: var(--accent-dim); }
mark { background: var(--hl); color: inherit; border-radius: 2px; }

/* tables */
.section { margin-bottom: 32px; scroll-margin-top: 12px; }
.section .eyebrow { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px; }
.section h2 { font-size: 12px; font-weight: 600; color: var(--text); margin-bottom: 2px; }
.section .for-str { font-size: 9px; color: var(--text2); margin-bottom: 6px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
thead th {
  background: var(--thead); position: sticky; top: 0; z-index: 1;
  padding: 6px 10px; text-align: right; font-weight: 500; color: var(--text2);
  border-bottom: 1px solid var(--border); font-size: 10px; white-space: nowrap;
}
thead th:first-child { text-align: left; }
tbody td {
  padding: 4px 10px; border-bottom: 1px solid var(--border); font-size: 10.5px;
  text-align: right; white-space: nowrap;
}
tbody td:first-child { text-align: left; color: var(--text2); }
tbody tr:nth-child(even) { background: var(--row-alt); }
tbody tr:hover { background: var(--accent-dim); }
td.hl { background: var(--hl); }

/* empty state */
#empty { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--muted); font-size: 12px; }
#empty.hidden { display: none; }

@media (max-width: 900px) {
  #hamburger { display: block; }
  #rail { position: fixed; top: 0; left: 0; height: 100%; }
  #rail.collapsed { transform: translateX(calc(-1 * var(--rail-w))); }
  #topbar { padding-left: 48px; }
}
</style>
</head>
<body>
<div id="app">
  <button id="hamburger" onclick="toggleRail()">&#9776;</button>
  <nav id="rail" class="collapsed">
    <div id="search-wrap"><input id="search" type="text" placeholder="Search reports..."></div>
    <div id="index"></div>
  </nav>
  <div style="display:flex;flex-direction:column;flex:1;overflow:hidden">
    <div id="topbar"></div>
    <div id="main">
      <div id="empty">Waiting for simulation report data&#8230;</div>
      <div id="content"></div>
    </div>
  </div>
</div>
<script type="module">
import { App } from '@modelcontextprotocol/ext-apps';

const $ = s => document.querySelector(s);
let railOpen = window.innerWidth > 900;
const rail = $('#rail');
const idx = $('#index');
const content = $('#content');
const search = $('#search');
let sectionEls = [], linkEls = [], groupState = {};

function toggleRail() { railOpen = !railOpen; rail.classList.toggle('collapsed', !railOpen); }
if (railOpen) rail.classList.remove('collapsed');

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function highlight(text, q) {
  if (!q) return esc(text);
  const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')})`, 'gi');
  return esc(text).replace(re, '<mark>$1</mark>');
}

function loadReport(data) {
  $('#empty').classList.add('hidden');

  // topbar
  const tb = $('#topbar');
  tb.innerHTML = `<span class="building">${esc(data.building_name || '')}</span>` +
    `<span>${esc(data.environment || '')}</span>` +
    `<span>EnergyPlus ${esc(data.energyplus_version || '')}</span>` +
    `<span>${esc(data.timestamp || '')}</span>` +
    `<span>${data.report_count ?? 0} reports &middot; ${data.table_count ?? 0} tables</span>`;

  buildContent(data.reports, '');
  buildIndex(data.reports, '');
  setupObserver();

  search.addEventListener('input', () => {
    const q = search.value.trim();
    buildContent(data.reports, q);
    buildIndex(data.reports, q);
    setupObserver();
  });
}

function buildContent(reports, q) {
  sectionEls = [];
  let html = '';
  reports.forEach((r, ri) => {
    r.tables.forEach((t, ti) => {
      const id = `s${ri}_${ti}`;
      const matchSection = !q || matches(r.report_name, q) || matches(t.table_name, q);
      const cellMatch = q && !matchSection ? hasMatchingCell(t, q) : false;
      if (q && !matchSection && !cellMatch) return;
      const forStr = t.for_string || r.for_string || '';
      html += `<div class="section" id="${id}">`;
      html += `<div class="eyebrow">${esc(r.report_name)}</div>`;
      html += `<h2>${esc(t.table_name)}</h2>`;
      if (forStr && forStr !== 'Entire Facility') html += `<div class="for-str">${esc(forStr)}</div>`;
      html += `<div class="table-wrap"><table><thead><tr><th></th>`;
      (t.columns || []).forEach(c => { html += `<th>${esc(c)}</th>`; });
      html += `</tr></thead><tbody>`;
      (t.rows || []).forEach(row => {
        html += `<tr><td>${q ? highlight(row.label, q) : esc(row.label)}</td>`;
        (row.values || []).forEach(v => {
          const cell = q ? highlight(v, q) : esc(v);
          const cls = q && matches(v, q) ? ' class="hl"' : '';
          html += `<td${cls}>${cell}</td>`;
        });
        html += `</tr>`;
      });
      html += `</tbody></table></div></div>`;
    });
  });
  content.innerHTML = html;
  sectionEls = [...content.querySelectorAll('.section')];
}

function buildIndex(reports, q) {
  linkEls = [];
  let html = '';
  reports.forEach((r, ri) => {
    const tables = r.tables.map((t, ti) => ({ t, ti })).filter(({ t }) => {
      if (!q) return true;
      if (matches(r.report_name, q) || matches(t.table_name, q)) return true;
      return hasMatchingCell(t, q);
    });
    if (q && tables.length === 0) return;
    const open = q ? true : (groupState[ri] ?? false);
    html += `<div class="rpt-group${open ? ' open' : ''}" data-ri="${ri}">`;
    html += `<button class="rpt-toggle" title="${esc(r.report_name)}">${q ? highlight(r.report_name, q) : esc(r.report_name)}</button>`;
    html += `<div class="rpt-tables">`;
    tables.forEach(({ t, ti }) => {
      const id = `s${ri}_${ti}`;
      html += `<div class="tbl-link" data-target="${id}">${q ? highlight(t.table_name, q) : esc(t.table_name)}</div>`;
    });
    html += `</div></div>`;
  });
  idx.innerHTML = html;
  linkEls = [...idx.querySelectorAll('.tbl-link')];

  idx.querySelectorAll('.rpt-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const g = btn.parentElement;
      const open = g.classList.toggle('open');
      groupState[g.dataset.ri] = open;
    });
  });
  linkEls.forEach(link => {
    link.addEventListener('click', () => {
      const el = document.getElementById(link.dataset.target);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

function matches(text, q) { return text && text.toLowerCase().includes(q.toLowerCase()); }

function hasMatchingCell(t, q) {
  return (t.rows || []).some(r =>
    matches(r.label, q) || (r.values || []).some(v => matches(v, q))
  );
}

let observer;
function setupObserver() {
  if (observer) observer.disconnect();
  observer = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        linkEls.forEach(l => l.classList.toggle('active', l.dataset.target === e.target.id));
      }
    });
  }, { root: $('#main'), rootMargin: '0px 0px -70% 0px', threshold: 0 });
  sectionEls.forEach(s => observer.observe(s));
}

function handleToolResult(result) {
  if (result?.structuredContent?.reports) { loadReport(result.structuredContent); return; }
  const textItem = result?.content?.find(item => item.type === 'text');
  if (!textItem) return;
  try {
    const data = JSON.parse(textItem.text);
    if (data.reports) loadReport(data);
  } catch (e) { console.debug('[report-viewer] Could not parse tool result', e); }
}

if (window.__IDFKIT_DATA__) loadReport(window.__IDFKIT_DATA__);

try {
  const app = new App({ name: 'idfkit Report Viewer', version: '1.0.0' });
  app.ontoolresult = handleToolResult;
  await app.connect();
} catch (e) { console.debug('[report-viewer] MCP Apps SDK not available', e); }
</script>
</body>
</html>
"""
