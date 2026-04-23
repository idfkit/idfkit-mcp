"""Self-contained browser-side EnergyPlus simulator HTML for the MCP Apps extension.

The UI resource registered at ``ui://idfkit/simulator.html`` runs an EnergyPlus
WASM build entirely inside a sandboxed iframe:

  1. Receives the IDF + EPW bytes from ``run_simulation_in_browser`` via the
     tool-call ``_meta.browser_run`` envelope.
  2. Loads the Emscripten glue (``energyplus.js`` + ``.wasm``) from
     ``/assets/energyplus/`` on the same origin.
  3. Runs the simulation on the main thread (fine for design-day workloads).
  4. Reads output files from MEMFS and calls ``upload_simulation_result``
     through the MCP Apps SDK so the server picks up the artifacts via the
     same session.

Kept in sync with the Python allowlist by templating
``_UPLOAD_ALLOWED_FILENAMES`` into the HTML at render time — see
``render_simulator_html``.
"""

from __future__ import annotations

import json

_SIMULATOR_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EnergyPlus Browser Simulator</title>
<script type="importmap">
{ "imports": { "@modelcontextprotocol/ext-apps": "https://unpkg.com/@modelcontextprotocol/ext-apps@1.0.1/app-with-deps" } }
</script>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #10141a; --panel: #13181f; --text: rgba(255,255,255,0.88);
  --text2: rgba(255,255,255,0.55); --muted: rgba(255,255,255,0.32);
  --accent: #5b9bd5; --accent-dim: rgba(91,155,213,0.15);
  --ok: #4caf7a; --warn: #e0a24c; --err: #e06c6c;
  --border: rgba(255,255,255,0.07);
  --font: 'SF Mono','Cascadia Code','JetBrains Mono','Fira Code',monospace;
}
/* Let the body grow with content so the SDK's auto-resize measurement
   (document.documentElement height at "fit-content") reflects the real
   content size rather than the iframe's allocated height. */
html, body { min-height: 100%; background: var(--bg); color: var(--text); font: 11px/1.5 var(--font); }
body { padding: 14px 18px; }
#app { display: flex; flex-direction: column; gap: 10px; }
header { display: flex; justify-content: space-between; align-items: baseline; flex-shrink: 0; }
header h1 { font-size: 12px; font-weight: 600; }
header .sub { font-size: 10px; color: var(--text2); }
.status {
  padding: 6px 10px; border-radius: 3px; background: var(--panel);
  border-left: 2px solid var(--accent); font-size: 10.5px; flex-shrink: 0;
}
.status.ok { border-left-color: var(--ok); }
.status.warn { border-left-color: var(--warn); }
.status.err { border-left-color: var(--err); }
.bar-wrap {
  background: var(--panel); border: 1px solid var(--border); border-radius: 3px;
  height: 14px; position: relative; overflow: hidden; flex-shrink: 0;
}
.bar-fill {
  position: absolute; inset: 0 auto 0 0; background: var(--accent);
  width: 0%; transition: width 0.25s ease;
}
.bar-label {
  position: absolute; inset: 0; display: flex; align-items: center;
  justify-content: center; font-size: 9.5px; color: var(--text); text-shadow: 0 0 2px #000;
}
#console {
  overflow-y: auto; background: var(--panel); border: 1px solid var(--border);
  border-radius: 3px; padding: 8px 10px; font-size: 10.5px; white-space: pre-wrap;
  color: var(--text2); min-height: 160px; max-height: 380px;
}
#console .line { padding: 1px 0; }
#console .line.err { color: var(--err); }
#console .line.warn { color: var(--warn); }
#console .line.info { color: var(--accent); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; flex-shrink: 0; }
.kpi { background: var(--panel); border: 1px solid var(--border); border-radius: 3px; padding: 6px 10px; }
.kpi .label { color: var(--muted); font-size: 9px; text-transform: uppercase; letter-spacing: 0.5px; }
.kpi .value { font-size: 12px; color: var(--text); }
.kpi .value.ok { color: var(--ok); }
.kpi .value.err { color: var(--err); }
footer { font-size: 9px; color: var(--muted); flex-shrink: 0; text-align: right; }
</style>
</head>
<body>
<div id="app">
  <header>
    <div>
      <h1>EnergyPlus Browser Simulator</h1>
      <div class="sub" id="sub">Waiting for simulation input&hellip;</div>
    </div>
    <div class="sub" id="run-id"></div>
  </header>
  <div class="status" id="status">Idle</div>
  <div class="bar-wrap"><div class="bar-fill" id="bar"></div><div class="bar-label" id="bar-label"></div></div>
  <div class="grid" id="kpis"></div>
  <div id="console"></div>
  <footer>Main-thread execution &middot; do not close this tab while the simulation runs.</footer>
</div>
<script type="module">
import { App } from '@modelcontextprotocol/ext-apps';

const CONFIG = __IDFKIT_SIMULATOR_CONFIG__;

const statusEl = document.getElementById('status');
const barEl = document.getElementById('bar');
const barLabelEl = document.getElementById('bar-label');
const subEl = document.getElementById('sub');
const runIdEl = document.getElementById('run-id');
const consoleEl = document.getElementById('console');
const kpisEl = document.getElementById('kpis');

let hasStarted = false;
let latestApp = null;

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = 'status' + (cls ? ' ' + cls : '');
}
function setProgress(pct, label) {
  const p = Math.max(0, Math.min(100, pct));
  barEl.style.width = p + '%';
  barLabelEl.textContent = label || (p.toFixed(0) + '%');
}
function log(text, cls) {
  const div = document.createElement('div');
  div.className = 'line' + (cls ? ' ' + cls : '');
  div.textContent = text;
  consoleEl.appendChild(div);
  consoleEl.scrollTop = consoleEl.scrollHeight;
}
function renderKpis(pairs) {
  kpisEl.innerHTML = '';
  for (const p of pairs) {
    const wrap = document.createElement('div');
    wrap.className = 'kpi';
    const l = document.createElement('div');
    l.className = 'label'; l.textContent = p.label;
    const v = document.createElement('div');
    v.className = 'value' + (p.cls ? ' ' + p.cls : ''); v.textContent = p.value;
    wrap.appendChild(l); wrap.appendChild(v);
    kpisEl.appendChild(wrap);
  }
}

function base64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function bytesToBase64(bytes) {
  let bin = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}

function loadEmscriptenScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('Failed to load ' + src));
    document.head.appendChild(s);
  });
}

// Fetch an EnergyPlus asset through the MCP Apps SDK's tool channel.
// Sandboxed MCP App iframes can't reliably cross-origin fetch() the
// server's static-asset route (CORS/CSP/mixed-content rules vary by host).
// Routing through callTool reuses the authorized postMessage transport
// that upload_simulation_result already uses successfully.
// Chunk size used when pulling large assets. MCP tool responses are atomic
// per call, so progress below the chunk granularity isn't possible — but
// a 1 MB stride gives ~30 ticks across the WASM binary, plenty for a
// responsive progress bar.
const ASSET_CHUNK_BYTES = 1024 * 1024;

async function fetchAssetViaMcp(filename, onProgress) {
  if (!latestApp) throw new Error('MCP Apps SDK not connected — cannot fetch ' + filename);
  const chunks = [];
  let received = 0;
  let total = 0;
  let offset = 0;
  while (true) {
    const result = await latestApp.callServerTool({
      name: 'fetch_energyplus_asset',
      arguments: { filename, offset, chunk_size: ASSET_CHUNK_BYTES },
    });
    const sc = result?.structuredContent;
    if (!sc || typeof sc.content_base64 !== 'string') {
      throw new Error('fetch_energyplus_asset returned no bytes for ' + filename);
    }
    const chunk = base64ToBytes(sc.content_base64);
    chunks.push(chunk);
    received += chunk.length;
    total = sc.total_size || total;
    if (onProgress) onProgress(received, total);
    offset += chunk.length;
    if (sc.is_last) break;
    if (chunk.length === 0) break; // defensive: avoid infinite loop on empty slice
  }
  if (chunks.length === 1) return chunks[0];
  const out = new Uint8Array(received);
  let p = 0;
  for (const c of chunks) { out.set(c, p); p += c.length; }
  return out;
}

function mbStr(bytes) {
  return (bytes / (1024 * 1024)).toFixed(1);
}

const WASM_CANDIDATE_NAMES = ['energyplus.js-26.1.wasm', 'energyplus.wasm'];
async function fetchWasmBinary(onProgress) {
  let lastErr = null;
  for (const name of WASM_CANDIDATE_NAMES) {
    try {
      log('Requesting ' + name);
      const bytes = await fetchAssetViaMcp(name, onProgress);
      log('Received ' + name + ' (' + bytes.length + ' bytes)', 'info');
      return bytes;
    } catch (e) {
      lastErr = e;
      log('  ' + (e && e.message || e), 'warn');
    }
  }
  throw lastErr || new Error('No WASM binary could be fetched');
}

async function loadWasmModule() {
  setStatus('Fetching EnergyPlus WASM binary…', null);
  setProgress(5, 'fetching wasm');

  // WASM download maps to the 5%-13% band; each chunk updates the bar.
  const wasmBinary = await fetchWasmBinary((got, total) => {
    if (total > 0) {
      const frac = got / total;
      setProgress(5 + frac * 8, mbStr(got) + ' / ' + mbStr(total) + ' MB');
    }
  });
  setProgress(14, 'fetching glue');

  setStatus('Fetching Emscripten glue…', null);
  log('Requesting energyplus.js');
  const jsBytes = await fetchAssetViaMcp('energyplus.js', (got, total) => {
    if (total > 0) setProgress(14 + (got / total) * 2, mbStr(got) + ' / ' + mbStr(total) + ' MB');
  });
  log('Received energyplus.js (' + jsBytes.length + ' bytes)', 'info');
  setProgress(16, 'initializing runtime');

  // Emscripten glue can only be loaded from a <script> tag, not eval'd,
  // without tripping CSP script-src rules. Blob URLs satisfy `blob:` in
  // script-src, which we declare on the UI resource's CSP.
  const jsBlob = new Blob([jsBytes], { type: 'application/javascript' });
  const jsBlobUrl = URL.createObjectURL(jsBlob);

  const readyPromise = new Promise((resolve, reject) => {
    const cfg = {
      wasmBinary,
      // locateFile still needed for Emscripten internals; returning a
      // harmless placeholder avoids it trying to go to the network.
      locateFile: (path) => path,
      print: (text) => log(text),
      printErr: (text) => log(text, 'err'),
      noExitRuntime: true,
      onAbort: (reason) => reject(new Error('Emscripten abort: ' + reason)),
      onRuntimeInitialized: () => {},
    };
    window.Module = cfg;

    const pollStart = Date.now();
    const pollTimeoutMs = 60000;
    const tryResolve = () => {
      const m = window.Module;
      if (m && typeof m.callMain === 'function' && m.FS) {
        resolve(m);
        return true;
      }
      return false;
    };
    cfg.onRuntimeInitialized = () => {
      if (!tryResolve()) {
        const t = setInterval(() => {
          if (tryResolve()) clearInterval(t);
          else if (Date.now() - pollStart > pollTimeoutMs) {
            clearInterval(t);
            reject(new Error('Timed out waiting for Module.callMain'));
          }
        }, 50);
      }
    };
  });

  try {
    await loadEmscriptenScript(jsBlobUrl);
    return await readyPromise;
  } finally {
    URL.revokeObjectURL(jsBlobUrl);
  }
}

async function loadRequiredDataFiles(mod) {
  setProgress(20, 'fetching IDD');
  const iddBytes = await fetchAssetViaMcp('Energy+.idd');
  mod.FS.writeFile('/Energy+.idd', iddBytes);
  log('Wrote /Energy+.idd (' + iddBytes.length + ' bytes)', 'info');

  try { mod.FS.mkdir('/datasets'); } catch {}
  const datasets = ['datasets/FluidPropertiesRefData.idf', 'datasets/GlycolPropertiesRefData.idf'];
  let stepPct = 23;
  for (const fullName of datasets) {
    setProgress(stepPct, 'fetching dataset');
    try {
      const b = await fetchAssetViaMcp(fullName);
      mod.FS.writeFile('/' + fullName, b);
    } catch (e) {
      log('Dataset ' + fullName + ' unavailable: ' + (e && e.message || e), 'warn');
    }
    stepPct += 2;
  }
}

function collectArtifacts(mod, allowlist) {
  const found = {};
  for (const name of allowlist) {
    try {
      const data = mod.FS.readFile('/output/' + name);
      found[name] = bytesToBase64(data);
    } catch { /* missing — skip */ }
  }
  return found;
}

async function runSimulation(payload) {
  if (hasStarted) return;
  hasStarted = true;

  const t0 = performance.now();
  runIdEl.textContent = 'run_id: ' + payload.run_id;
  subEl.textContent = (payload.annual ? 'Annual' : payload.design_day ? 'Design-day' : 'Run-period')
    + ' simulation · ' + (payload.expected_energyplus_version || 'unknown version');
  setStatus('Preparing…', null);
  setProgress(2, 'starting');

  try {
    const mod = await loadWasmModule();
    await loadRequiredDataFiles(mod);

    setProgress(28, 'writing inputs');
    const idfBytes = new TextEncoder().encode(payload.idf);
    mod.FS.writeFile('/input.idf', idfBytes);
    log('Wrote /input.idf (' + idfBytes.length + ' bytes)', 'info');

    let hasEpw = false;
    if (payload.epw) {
      const epwBytes = base64ToBytes(payload.epw);
      mod.FS.writeFile('/weather.epw', epwBytes);
      log('Wrote /weather.epw (' + epwBytes.length + ' bytes)', 'info');
      hasEpw = true;
    }

    try { mod.FS.mkdir('/output'); } catch {}

    const args = ['-d', '/output', '-i', '/Energy+.idd'];
    if (hasEpw) args.push('-w', '/weather.epw');
    if (payload.annual) args.push('-a');
    if (payload.design_day) args.push('-D');
    args.push('/input.idf');

    setStatus('Running EnergyPlus…', null);
    setProgress(40, 'callMain');
    log('callMain ' + args.join(' '), 'info');

    let exitCode = 0;
    let callMainError = null;
    try {
      exitCode = mod.callMain(args);
    } catch (e) {
      callMainError = e instanceof Error ? e : new Error(String(e));
      const m = callMainError.message.match(/exit\((\d+)\)/);
      exitCode = m && m[1] ? parseInt(m[1], 10) : 1;
    }
    setProgress(80, 'collecting outputs');
    log('EnergyPlus exited with code ' + exitCode, exitCode === 0 ? 'info' : 'err');

    const files = collectArtifacts(mod, CONFIG.allowed_output_filenames);
    const fileCount = Object.keys(files).length;
    if (fileCount === 0) {
      log('EnergyPlus produced no output files — nothing to upload.', 'err');
      setStatus('Simulation produced no output. See console for details.', 'err');
      setProgress(100, 'failed');
      return;
    }
    // Failed runs may ship eplusout.err (and .end) without .sql — upload
    // whatever we have so the server can still surface diagnostics.
    if (!files['eplusout.sql']) {
      log('No eplusout.sql produced; uploading diagnostic artifacts: '
        + Object.keys(files).join(', '), 'warn');
    }

    const runtimeSec = (performance.now() - t0) / 1000;
    setStatus('Uploading ' + fileCount + ' artifact(s) to the server…', null);
    setProgress(90, 'uploading');

    if (!latestApp) throw new Error('MCP Apps SDK not connected — cannot upload artifacts.');
    const uploadArgs = {
      files,
      run_id: payload.run_id,
      runtime_seconds: runtimeSec,
    };
    if (payload.expected_energyplus_version) {
      uploadArgs.energyplus_version = payload.expected_energyplus_version;
    }
    const uploadResult = await latestApp.callServerTool({
      name: CONFIG.upload_tool_name,
      arguments: uploadArgs,
    });

    const sc = uploadResult?.structuredContent || {};
    const success = sc.success === true && exitCode === 0 && !callMainError;
    renderKpis([
      { label: 'exit code', value: String(exitCode), cls: exitCode === 0 ? 'ok' : 'err' },
      { label: 'runtime', value: runtimeSec.toFixed(2) + ' s' },
      { label: 'artifacts', value: Object.keys(files).length + ' file(s)' },
      { label: 'fatal', value: String(sc.errors?.fatal ?? '—'), cls: (sc.errors?.fatal || 0) > 0 ? 'err' : 'ok' },
      { label: 'severe', value: String(sc.errors?.severe ?? '—') },
      { label: 'warnings', value: String(sc.errors?.warnings ?? '—') },
    ]);
    setProgress(100, success ? 'done' : 'done (with errors)');
    setStatus(success
      ? 'Simulation complete. Results available via idfkit://simulation/results.'
      : 'Simulation finished with errors — see console and results resource.',
      success ? 'ok' : 'warn');
    log('upload_simulation_result output_directory=' + (sc.output_directory || '?'), 'info');
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    log('FATAL: ' + msg, 'err');
    setStatus('Simulation aborted: ' + msg, 'err');
    setProgress(100, 'failed');
  }
}

function extractBrowserRun(meta) {
  if (!meta) return null;
  if (meta.browser_run) return meta.browser_run;
  if (meta._meta && meta._meta.browser_run) return meta._meta.browser_run;
  return null;
}
function handleToolResult(result) {
  const fromMeta = extractBrowserRun(result?._meta || result?.meta);
  const fromStructured = result?.structuredContent?.browser_run;
  const payload = fromMeta || fromStructured;
  if (!payload) {
    log('Tool result did not contain browser_run payload — ignoring.', 'warn');
    return;
  }
  runSimulation(payload);
}

try {
  const app = new App({ name: 'idfkit Browser Simulator', version: '1.0.0' });
  app.ontoolresult = handleToolResult;
  await app.connect();
  latestApp = app;
} catch (e) {
  log('MCP Apps SDK failed to connect: ' + (e && e.message || e), 'err');
}

// Server-side injection fallback for manual testing / bespoke hosts.
if (window.__IDFKIT_BROWSER_RUN__) {
  runSimulation(window.__IDFKIT_BROWSER_RUN__);
}
</script>
</body>
</html>
"""


def render_simulator_html(*, allowed_output_filenames: list[str], upload_tool_name: str) -> str:
    """Render the simulator HTML with the runtime config templated in.

    The allowlist is mirrored from Python so the iframe never attempts to
    read a filename the server would reject.
    """
    config = {
        "allowed_output_filenames": sorted(allowed_output_filenames),
        "upload_tool_name": upload_tool_name,
    }
    return _SIMULATOR_HTML_TEMPLATE.replace("__IDFKIT_SIMULATOR_CONFIG__", json.dumps(config))
