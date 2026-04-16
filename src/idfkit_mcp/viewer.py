"""Self-contained Three.js geometry viewer HTML for the MCP Apps extension."""

from __future__ import annotations

VIEWER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>idfkit — Geometry Viewer</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    /* -- Viewport -- */
    --canvas-bg: #0e0e10;

    /* -- Material palette -- */
    --wall:     #8a8a8a;
    --floor:    #a08b6c;
    --roof:     #5a6672;
    --ceiling:  #6b6b6b;
    --window:   #7ec8d9;
    --door:     #9e8a72;
    --shading:  #4a5a4a;

    /* -- UI chrome -- */
    --chrome-bg:     rgba(20, 20, 22, 0.85);
    --chrome-border: rgba(255, 255, 255, 0.08);
    --chrome-hover:  rgba(255, 255, 255, 0.06);
    --text-primary:  rgba(255, 255, 255, 0.88);
    --text-secondary: rgba(255, 255, 255, 0.50);
    --text-muted:    rgba(255, 255, 255, 0.30);
    --accent:        #e8834a;
    --accent-dim:    rgba(232, 131, 74, 0.25);
  }

  /* min-height floors the autoResize max-content measurement the MCP Apps SDK
     reports to the host, otherwise the 100%-chained children collapse and the
     host sizes the iframe too short for a 3D viewport. */
  html, body { width: 100%; height: 100%; min-height: 560px; overflow: hidden; background: var(--canvas-bg); }

  #viewport { width: 100%; height: 100%; min-height: 560px; display: block; }

  /* -- Floating toolbar -- */
  .toolbar {
    position: absolute;
    top: 12px;
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

  /* -- Surface type legend / toggles -- */
  .legend {
    position: absolute;
    bottom: 12px;
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

  .legend button {
    font-family: 'SF Mono', 'Cascadia Code', 'JetBrains Mono', monospace;
    font-size: 10px;
    color: var(--text-secondary);
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 5px;
    transition: background 0.15s, color 0.15s, opacity 0.2s;
  }
  .legend button:hover { background: var(--chrome-hover); color: var(--text-primary); }
  .legend button.hidden { opacity: 0.35; }

  .legend .swatch {
    width: 8px;
    height: 8px;
    border-radius: 2px;
    flex-shrink: 0;
  }

  /* -- Info panel (click-inspect) -- */
  .info-panel {
    position: absolute;
    top: 12px;
    right: 12px;
    width: 240px;
    background: var(--chrome-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--chrome-border);
    border-radius: 6px;
    padding: 14px;
    z-index: 10;
    display: none;
    font-family: 'SF Mono', 'Cascadia Code', 'JetBrains Mono', monospace;
  }

  .info-panel.visible { display: block; }

  .info-panel .info-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 10px;
    letter-spacing: -0.02em;
    word-break: break-all;
  }

  .info-panel .info-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 3px 0;
  }

  .info-panel .info-label {
    font-size: 10px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .info-panel .info-value {
    font-size: 11px;
    color: var(--text-secondary);
    text-align: right;
  }

  .info-panel .info-close {
    position: absolute;
    top: 8px;
    right: 10px;
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 14px;
    cursor: pointer;
    padding: 2px 4px;
    line-height: 1;
  }
  .info-panel .info-close:hover { color: var(--text-secondary); }

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

  /* -- Zone selector dropdown -- */
  .zone-selector {
    position: absolute;
    top: 52px;
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
  }
  .zone-selector.visible { display: block; }

  .zone-selector button {
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
  }
  .zone-selector button:hover { background: var(--chrome-hover); color: var(--text-primary); }
  .zone-selector button.active { color: var(--accent); }
</style>
</head>
<body>

<canvas id="viewport"></canvas>

<!-- Toolbar -->
<div class="toolbar">
  <button id="btn-solid" class="active">Solid</button>
  <button id="btn-wireframe">Wire</button>
  <button id="btn-xray">X-Ray</button>
  <div class="sep"></div>
  <button id="btn-zones">Zones</button>
  <div class="sep"></div>
  <button id="btn-reset">Reset</button>
</div>

<!-- Zone selector (shown when Zones is active) -->
<div class="zone-selector" id="zone-selector"></div>

<!-- Surface type legend -->
<div class="legend" id="legend"></div>

<!-- Click-inspect panel -->
<div class="info-panel" id="info-panel">
  <button class="info-close" id="info-close">&times;</button>
  <div class="info-title" id="info-title"></div>
  <div id="info-rows"></div>
</div>

<!-- Stats -->
<div class="stats" id="stats"></div>

<script type="importmap">
{
  "imports": {
    "three": "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js",
    "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/",
    "@modelcontextprotocol/ext-apps": "https://unpkg.com/@modelcontextprotocol/ext-apps@1.0.1/app-with-deps"
  }
}
</script>

<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { App } from '@modelcontextprotocol/ext-apps';

// ── Color palettes ──────────────────────────────────────────────────

const TYPE_COLORS = {
  'Wall':     0x8a8a8a,
  'Floor':    0xa08b6c,
  'Roof':     0x5a6672,
  'Ceiling':  0x6b6b6b,
  'Window':   0x7ec8d9,
  'Door':     0x9e8a72,
  'GlassDoor':0x7ec8d9,
  'TubularDaylightDome':  0x7ec8d9,
  'TubularDaylightDiffuser': 0x7ec8d9,
};

const SHADING_COLOR = 0x4a5a4a;

// Muted, distinguishable zone hues
const ZONE_HUES = [0.06, 0.14, 0.55, 0.75, 0.35, 0.92, 0.45, 0.65, 0.02, 0.82];

function surfaceColor(surface, colorBy, zoneIndex) {
  if (colorBy === 'zone' && surface.zone) {
    const idx = zoneIndex[surface.zone] ?? 0;
    const hue = ZONE_HUES[idx % ZONE_HUES.length];
    return new THREE.Color().setHSL(hue, 0.35, 0.45);
  }
  if (surface.objectType.startsWith('Shading:')) return new THREE.Color(SHADING_COLOR);
  return new THREE.Color(TYPE_COLORS[surface.surfaceType] ?? 0x777777);
}

function surfaceOpacity(surface) {
  if (['Window', 'GlassDoor', 'TubularDaylightDome', 'TubularDaylightDiffuser']
        .includes(surface.surfaceType)) return 0.4;
  if (surface.objectType.startsWith('Shading:')) return 0.6;
  return 0.85;
}

// ── Triangulation ───────────────────────────────────────────────────

function triangulatePoly(vertices) {
  // Fan triangulation from vertex 0 — works for convex EnergyPlus surfaces.
  const indices = [];
  for (let i = 1; i < vertices.length - 1; i++) {
    indices.push(0, i, i + 1);
  }
  return indices;
}

// ── Build scene ─────────────────────────────────────────────────────

let scene, camera, renderer, controls;
let surfaceMeshes = [];     // { mesh, data, edges }
let modelData = null;
let selectedMesh = null;
let hoveredMesh = null;
let renderMode = 'solid';   // solid | wireframe | xray
let activeZone = null;       // null = all zones
const hiddenTypes = new Set();
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();

function init() {
  const canvas = document.getElementById('viewport');

  // Scene
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0e0e10);

  // Camera
  camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 2000);

  // Renderer
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  // Controls
  controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.rotateSpeed = 0.6;
  controls.panSpeed = 0.5;
  controls.zoomSpeed = 0.8;

  // Lighting — soft and directional, like a drafting table
  const ambient = new THREE.AmbientLight(0xffffff, 0.5);
  scene.add(ambient);

  const dirLight = new THREE.DirectionalLight(0xffffff, 0.7);
  dirLight.position.set(30, 50, 40);
  scene.add(dirLight);

  const fillLight = new THREE.DirectionalLight(0xb0c0d0, 0.3);
  fillLight.position.set(-20, 30, -10);
  scene.add(fillLight);

  // Events
  window.addEventListener('resize', onResize);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('click', onClick);

  // Toolbar
  document.getElementById('btn-solid').addEventListener('click', () => setRenderMode('solid'));
  document.getElementById('btn-wireframe').addEventListener('click', () => setRenderMode('wireframe'));
  document.getElementById('btn-xray').addEventListener('click', () => setRenderMode('xray'));
  document.getElementById('btn-zones').addEventListener('click', toggleZoneSelector);
  document.getElementById('btn-reset').addEventListener('click', resetView);
  document.getElementById('info-close').addEventListener('click', closeInfoPanel);

  animate();
}

function buildModel(data) {
  modelData = data;

  // Clear previous
  surfaceMeshes.forEach(({ mesh, edges }) => {
    scene.remove(mesh);
    if (edges) scene.remove(edges);
  });
  surfaceMeshes = [];

  const zoneIndex = {};
  data.zones.forEach((z, i) => { zoneIndex[z] = i; });

  const bbox = new THREE.Box3();

  data.surfaces.forEach(surface => {
    const verts = surface.vertices;
    if (verts.length < 3) return;

    // Build geometry
    const positions = new Float32Array(verts.length * 3);
    verts.forEach((v, i) => {
      positions[i * 3]     = v[0];
      positions[i * 3 + 1] = v[2]; // swap Y/Z for Three.js (Y-up)
      positions[i * 3 + 2] = -v[1];
    });

    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    const indices = triangulatePoly(verts);
    geom.setIndex(indices);
    geom.computeVertexNormals();

    const color = surfaceColor(surface, data.colorBy, zoneIndex);
    const opacity = surfaceOpacity(surface);

    const mat = new THREE.MeshStandardMaterial({
      color,
      transparent: opacity < 1.0,
      opacity,
      side: THREE.DoubleSide,
      roughness: 0.7,
      metalness: 0.05,
      depthWrite: opacity >= 1.0,
    });

    const mesh = new THREE.Mesh(geom, mat);
    mesh.userData = { surface, baseColor: color.clone(), baseOpacity: opacity };
    scene.add(mesh);

    // Edge wireframe — subtle
    const edgeGeom = new THREE.EdgesGeometry(geom, 15);
    const edgeMat = new THREE.LineBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.08,
    });
    const edges = new THREE.LineSegments(edgeGeom, edgeMat);
    scene.add(edges);

    surfaceMeshes.push({ mesh, data: surface, edges });

    // Expand bounding box
    for (let i = 0; i < verts.length; i++) {
      bbox.expandByPoint(new THREE.Vector3(
        positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]
      ));
    }
  });

  // Fit camera
  const center = new THREE.Vector3();
  bbox.getCenter(center);
  const size = new THREE.Vector3();
  bbox.getSize(size);
  const maxDim = Math.max(size.x, size.y, size.z);
  const dist = maxDim * 1.8;

  camera.position.set(center.x + dist * 0.6, center.y + dist * 0.5, center.z + dist * 0.7);
  controls.target.copy(center);
  controls.update();

  // Build UI
  buildLegend(data, zoneIndex);
  buildZoneSelector(data);
  document.getElementById('stats').textContent =
    `${data.surfaces.length} surfaces · ${data.zones.length} zones`;
}

// ── Legend ───────────────────────────────────────────────────────────

function buildLegend(data, zoneIndex) {
  const legend = document.getElementById('legend');
  legend.innerHTML = '';

  if (data.colorBy === 'zone') {
    data.zones.forEach(zone => {
      const hue = ZONE_HUES[(zoneIndex[zone] ?? 0) % ZONE_HUES.length];
      const color = new THREE.Color().setHSL(hue, 0.35, 0.45);
      addLegendButton(legend, zone, '#' + color.getHexString(), zone, 'zone');
    });
  } else {
    const types = ['Wall', 'Floor', 'Roof', 'Ceiling', 'Window', 'Door'];
    const hasShading = data.surfaces.some(s => s.objectType.startsWith('Shading:'));

    types.forEach(t => {
      const hex = TYPE_COLORS[t];
      if (hex !== undefined && data.surfaces.some(s => s.surfaceType === t)) {
        addLegendButton(legend, t, '#' + new THREE.Color(hex).getHexString(), t, 'type');
      }
    });

    if (hasShading) {
      addLegendButton(legend, 'Shading', '#' + new THREE.Color(SHADING_COLOR).getHexString(), 'Shading', 'type');
    }
  }
}

function addLegendButton(container, label, color, key, kind) {
  const btn = document.createElement('button');
  btn.innerHTML = `<span class="swatch" style="background:${color}"></span>${label}`;
  btn.dataset.key = key;
  btn.dataset.kind = kind;
  btn.addEventListener('click', () => toggleTypeVisibility(btn, key, kind));
  container.appendChild(btn);
}

function toggleTypeVisibility(btn, key, kind) {
  const isHidden = btn.classList.toggle('hidden');
  surfaceMeshes.forEach(({ mesh, data, edges }) => {
    let match = false;
    if (kind === 'type') {
      match = data.objectType.startsWith('Shading:')
        ? key === 'Shading'
        : data.surfaceType === key;
    } else {
      match = data.zone === key;
    }
    if (match) {
      mesh.visible = !isHidden;
      if (edges) edges.visible = !isHidden;
    }
  });
}

// ── Zone selector ───────────────────────────────────────────────────

function buildZoneSelector(data) {
  const container = document.getElementById('zone-selector');
  container.innerHTML = '';

  const allBtn = document.createElement('button');
  allBtn.textContent = 'All Zones';
  allBtn.classList.add('active');
  allBtn.addEventListener('click', () => selectZone(null, container));
  container.appendChild(allBtn);

  data.zones.forEach(zone => {
    const btn = document.createElement('button');
    btn.textContent = zone;
    btn.dataset.zone = zone;
    btn.addEventListener('click', () => selectZone(zone, container));
    container.appendChild(btn);
  });
}

function toggleZoneSelector() {
  const el = document.getElementById('zone-selector');
  const btn = document.getElementById('btn-zones');
  const visible = el.classList.toggle('visible');
  btn.classList.toggle('active', visible);
  if (!visible) selectZone(null, el);
}

function selectZone(zone, container) {
  activeZone = zone;
  container.querySelectorAll('button').forEach(b => {
    b.classList.toggle('active', zone ? b.dataset.zone === zone : !b.dataset.zone);
  });

  surfaceMeshes.forEach(({ mesh, data, edges }) => {
    if (zone === null) {
      // Restore — respect legend toggles
      const legendHidden = isLegendHidden(data);
      mesh.visible = !legendHidden;
      if (edges) edges.visible = !legendHidden;
      mesh.material.opacity = mesh.userData.baseOpacity;
    } else if (data.zone === zone) {
      mesh.visible = true;
      if (edges) edges.visible = true;
      mesh.material.opacity = mesh.userData.baseOpacity;
    } else {
      // Fade non-zone surfaces
      mesh.visible = true;
      if (edges) edges.visible = true;
      mesh.material.opacity = 0.06;
    }
  });
}

function isLegendHidden(surface) {
  const legend = document.getElementById('legend');
  const buttons = legend.querySelectorAll('button.hidden');
  for (const btn of buttons) {
    const key = btn.dataset.key;
    const kind = btn.dataset.kind;
    if (kind === 'type') {
      if (surface.objectType.startsWith('Shading:') && key === 'Shading') return true;
      if (surface.surfaceType === key) return true;
    } else if (kind === 'zone') {
      if (surface.zone === key) return true;
    }
  }
  return false;
}

// ── Render modes ────────────────────────────────────────────────────

function setRenderMode(mode) {
  renderMode = mode;
  document.querySelectorAll('#btn-solid, #btn-wireframe, #btn-xray').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + mode).classList.add('active');

  surfaceMeshes.forEach(({ mesh, edges }) => {
    const { baseOpacity } = mesh.userData;
    switch (mode) {
      case 'solid':
        mesh.material.wireframe = false;
        mesh.material.opacity = baseOpacity;
        mesh.visible = true;
        if (edges) { edges.material.opacity = 0.08; edges.visible = true; }
        break;
      case 'wireframe':
        mesh.material.wireframe = true;
        mesh.material.opacity = 0.6;
        mesh.visible = true;
        if (edges) edges.visible = false;
        break;
      case 'xray':
        mesh.material.wireframe = false;
        mesh.material.opacity = 0.12;
        mesh.visible = true;
        if (edges) { edges.material.opacity = 0.2; edges.visible = true; }
        break;
    }
  });
}

// ── Interaction ─────────────────────────────────────────────────────

function onPointerMove(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

  raycaster.setFromCamera(pointer, camera);
  const meshes = surfaceMeshes.filter(s => s.mesh.visible).map(s => s.mesh);
  const intersects = raycaster.intersectObjects(meshes, false);

  // Un-hover previous
  if (hoveredMesh && hoveredMesh !== selectedMesh) {
    hoveredMesh.material.emissive.setHex(0x000000);
  }

  if (intersects.length > 0) {
    hoveredMesh = intersects[0].object;
    if (hoveredMesh !== selectedMesh) {
      hoveredMesh.material.emissive.setHex(0x1a1a1a);
    }
    renderer.domElement.style.cursor = 'pointer';
  } else {
    hoveredMesh = null;
    renderer.domElement.style.cursor = 'default';
  }
}

function onClick(event) {
  // Ignore clicks on UI elements
  if (event.target !== renderer.domElement) return;

  raycaster.setFromCamera(pointer, camera);
  const meshes = surfaceMeshes.filter(s => s.mesh.visible).map(s => s.mesh);
  const intersects = raycaster.intersectObjects(meshes, false);

  // Deselect previous
  if (selectedMesh) {
    selectedMesh.material.emissive.setHex(0x000000);
    selectedMesh.material.color.copy(selectedMesh.userData.baseColor);
    selectedMesh = null;
  }

  if (intersects.length > 0) {
    selectedMesh = intersects[0].object;
    selectedMesh.material.emissive.setHex(0x2a1a0a);
    showInfoPanel(selectedMesh.userData.surface);
  } else {
    closeInfoPanel();
  }
}

function showInfoPanel(surface) {
  const panel = document.getElementById('info-panel');
  const title = document.getElementById('info-title');
  const rows = document.getElementById('info-rows');

  title.textContent = surface.name || '(unnamed)';
  rows.innerHTML = '';

  const fields = [
    ['Type', surface.surfaceType],
    ['Object', surface.objectType.split(':')[0]],
    ['Zone', surface.zone || '—'],
    ['Boundary', surface.boundary || '—'],
    ['Construction', surface.construction || '—'],
    ['Area', surface.area + ' m\u00b2'],
    ['Tilt', surface.tilt + '\u00b0'],
    ['Azimuth', surface.azimuth + '\u00b0'],
  ];

  fields.forEach(([label, value]) => {
    const row = document.createElement('div');
    row.className = 'info-row';
    row.innerHTML = `<span class="info-label">${label}</span><span class="info-value">${value}</span>`;
    rows.appendChild(row);
  });

  panel.classList.add('visible');
}

function closeInfoPanel() {
  document.getElementById('info-panel').classList.remove('visible');
  if (selectedMesh) {
    selectedMesh.material.emissive.setHex(0x000000);
    selectedMesh.material.color.copy(selectedMesh.userData.baseColor);
    selectedMesh = null;
  }
}

// ── Camera reset ────────────────────────────────────────────────────

function resetView() {
  if (!modelData) return;
  // Recompute bounding box
  const bbox = new THREE.Box3();
  surfaceMeshes.forEach(({ mesh }) => {
    if (mesh.visible) {
      mesh.geometry.computeBoundingBox();
      const b = mesh.geometry.boundingBox.clone();
      b.applyMatrix4(mesh.matrixWorld);
      bbox.union(b);
    }
  });

  const center = new THREE.Vector3();
  bbox.getCenter(center);
  const size = new THREE.Vector3();
  bbox.getSize(size);
  const maxDim = Math.max(size.x, size.y, size.z);
  const dist = maxDim * 1.8;

  camera.position.set(center.x + dist * 0.6, center.y + dist * 0.5, center.z + dist * 0.7);
  controls.target.copy(center);
  controls.update();
}

// ── Resize ──────────────────────────────────────────────────────────

function onResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}

// ── Render loop ─────────────────────────────────────────────────────

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}

// ── MCP Apps integration ────────────────────────────────────────────

init();

// Parse geometry data from a tool result content array.
function handleToolResult({ content }) {
  const textItem = content?.find(c => c.type === 'text');
  if (!textItem) return;
  try {
    const data = JSON.parse(textItem.text);
    if (data.surfaces) buildModel(data);
  } catch (e) {
    console.debug('[idfkit-viewer] Could not parse tool result', e);
  }
}

// Load embedded data immediately (for standalone testing / when connect stalls).
if (window.__IDFKIT_DATA__) {
  buildModel(window.__IDFKIT_DATA__);
}

// Connect via the official MCP Apps SDK.
try {
  const app = new App({ name: 'idfkit Geometry Viewer', version: '1.0.0' });
  app.ontoolresult = handleToolResult;
  await app.connect();
} catch (e) { console.debug('[idfkit-geometry-viewer] MCP Apps SDK not available', e); }
</script>
</body>
</html>
"""
