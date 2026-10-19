import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GRID_SIZE, demoPixels, voxelize, nearestVisibleTile, findTilePath, buildBridge, tileHeight, exportThreeFactory, serializeWorld, deserializeWorld, previewWorldPixels } from './world-data.mjs';

const $ = id => document.getElementById(id);
const canvas = $('viewport');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, preserveDrawingBuffer: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.35;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x08121f);
scene.fog = new THREE.FogExp2(0x08121f, .012);
const camera = new THREE.PerspectiveCamera(48, 1, .1, 250);
const HOME = new THREE.Vector3(32, 34, 42);
camera.position.copy(HOME);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = .07;
controls.minDistance = 15;
controls.maxDistance = 90;
controls.maxPolarAngle = Math.PI * .48;
controls.target.set(0, 0, 0);
controls.autoRotateSpeed = .7;

const ambient = new THREE.HemisphereLight(0xd5e7ff, 0x2b4551, 2.3);
const sun = new THREE.DirectionalLight(0xffddb4, 3.2);
sun.position.set(-15, 30, 22);
scene.add(ambient, sun);

const plinth = new THREE.Mesh(
  new THREE.BoxGeometry(GRID_SIZE + 1.35, .8, GRID_SIZE + 1.35),
  new THREE.MeshStandardMaterial({ color: 0x122e3a, roughness: .56, metalness: .24 }),
);
plinth.position.y = -.48;
scene.add(plinth);
const rim = new THREE.LineSegments(
  new THREE.EdgesGeometry(new THREE.BoxGeometry(GRID_SIZE + 1.42, .82, GRID_SIZE + 1.42)),
  new THREE.LineBasicMaterial({ color: 0x4fbfbb, transparent: true, opacity: .45 }),
);
rim.position.y = -.48;
scene.add(rim);

const stars = new THREE.BufferGeometry();
const starPositions = new Float32Array(300 * 3);
for (let i = 0; i < 300; i++) {
  const seed = i * 23.174;
  const angle = seed * 2.39996;
  const radius = 42 + ((i * 47) % 82);
  starPositions[3 * i] = Math.cos(angle) * radius;
  starPositions[3 * i + 1] = 13 + ((i * 31) % 78);
  starPositions[3 * i + 2] = Math.sin(angle) * radius;
}
stars.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
const starField = new THREE.Points(stars, new THREE.PointsMaterial({ color: 0xc8e9ff, size: .14, transparent: true, opacity: .75, sizeAttenuation: true }));
scene.add(starField);

let data = null;
let relief = 1;
let world = null;
let cells = [];
let beacons = [];
let collected = 0;
let night = false;
let themeIndex = 0;
const themes = [['sunset', 'Sunset coast'], ['forest', 'Emerald valley'], ['cosmic', 'Nebula bloom']];
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const helper = new THREE.Object3D();
const activeRipples = [];
const beaconGeometry = new THREE.IcosahedronGeometry(.43, 1);
const beaconMaterial = new THREE.MeshStandardMaterial({ color: 0xffdba0, emissive: 0xffae35, emissiveIntensity: 2.6, metalness: .2, roughness: .2 });
const colorHelper = new THREE.Color();
let messageTimer;
let bridgeMode = false;
let bridgeStart = -1;
let undoWorlds = [];
// Independent scout group; geometry remains code-only and is reused across worlds.
const scout = new THREE.Group();
const scoutBody = new THREE.Mesh(
  new THREE.IcosahedronGeometry(.35, 1),
  new THREE.MeshStandardMaterial({ color: 0x9deed7, emissive: 0x16bca7, emissiveIntensity: 1.7, roughness: .2 }),
);
const scoutHalo = new THREE.Mesh(
  new THREE.TorusGeometry(.48, .042, 5, 24),
  new THREE.MeshBasicMaterial({ color: 0xb9ffeb }),
);
scoutHalo.rotation.x = Math.PI / 2;
scout.add(scoutBody, scoutHalo);
scene.add(scout);
let scoutCell = -1;
let scoutDestination = -1;
let scoutQueue = [];
let scoutFraction = 0;
const scoutFrom = new THREE.Vector3();
const scoutTo = new THREE.Vector3();


function announce(message) {
  $('notice').textContent = message;
  $('notice').classList.add('show');
  window.clearTimeout(messageTimer);
  messageTimer = window.setTimeout(() => $('notice').classList.remove('show'), 2600);
}

function positionOf(i, h) {
  const n = data.size;
  return [(i % n) - (n - 1) / 2, h / 2, Math.floor(i / n) - (n - 1) / 2];
}

function redrawTiles(time = 0) {
  if (!world || !data) return;
  for (let k = 0; k < cells.length; k++) {
    const i = cells[k];
    const h = tileHeight(data.heights[i], relief);
    const [x, , z] = positionOf(i, h);
    let push = 0;
    for (const ripple of activeRipples) {
      const age = (time - ripple.born) / 1000;
      if (age < 0 || age > 2.4) continue;
      const dist = Math.hypot(x - ripple.x, z - ripple.z);
      const wave = Math.exp(-((dist - age * 9) ** 2) * .5);
      push += wave * (1 - age / 2.4) * 1.45;
    }
    helper.position.set(x, h / 2 + push, z);
    helper.scale.set(1, h, 1);
    helper.updateMatrix();
    world.setMatrixAt(k, helper.matrix);
  }
  world.instanceMatrix.needsUpdate = true;
  world.computeBoundingSphere();
}

function addRipple(x, z) {
  if (activeRipples.length === 12) activeRipples.shift();
  activeRipples.push({ x, z, born: performance.now() });
}

function scoutTilePosition(cell, target = new THREE.Vector3()) {
  const h = tileHeight(data.heights[cell], relief);
  const [x, , z] = positionOf(cell, h);
  return target.set(x, h + .46, z);
}

function resetScout(preferredCell = -1) {
  const approximateSpawn = (data.size - 1) * data.size + Math.floor(data.size / 2);
  scoutCell = preferredCell >= 0 && data.visible[preferredCell] ? preferredCell : nearestVisibleTile(data, approximateSpawn);
  scout.visible = scoutCell !== -1;
  scoutDestination = -1;
  scoutQueue = [];
  scoutFraction = 0;
  if (scout.visible) scoutTilePosition(scoutCell, scout.position);
  $('scout-status').textContent = scout.visible
    ? 'Tap a tile to guide your glowing scout · collect the beacons'
    : 'No visible terrain: upload a less transparent image or remix';
}

function beginScoutStep() {
  if (!scoutQueue.length) {
    scoutDestination = -1;
    $('scout-status').textContent = 'Scout arrived · tap another tile to explore';
    return;
  }
  scoutDestination = scoutQueue.shift();
  scoutFrom.copy(scout.position);
  scoutTilePosition(scoutDestination, scoutTo);
  scoutFraction = 0;
}

function routeScout(goal) {
  if (scoutCell === -1) return;
  const path = findTilePath(data, scoutCell, goal);
  if (!path.length) {
    announce('That tile is on a disconnected island. Try another.');
    return;
  }
  if (path.length === 1) {
    addRipple(scout.position.x, scout.position.z);
    return;
  }
  scoutQueue = path.slice(1);
  beginScoutStep();
  $('scout-status').textContent = `Scout hiking · ${path.length - 1} tile journey`;
}

function collectBeacon(beacon) {
  if (!beacon.visible) return;
  beacon.visible = false;
  collected++;
  $('count').textContent = `${collected} / ${beacons.length}`;
  addRipple(beacon.position.x, beacon.position.z);
  announce(collected === beacons.length ? 'World complete! Remix to explore another island.' : `${collected} beacon${collected === 1 ? '' : 's'} discovered.`);
}

function animateScout(dt, reducedMotion) {
  if (scoutDestination === -1) return;
  scoutFraction = Math.min(1, scoutFraction + dt * (reducedMotion ? 40 : 4));
  scout.position.lerpVectors(scoutFrom, scoutTo, scoutFraction);
  scout.position.y += reducedMotion ? 0 : Math.sin(scoutFraction * Math.PI) * .28;
  if (scoutFraction === 1) {
    scoutCell = scoutDestination;
    for (const beacon of beacons) if (beacon.userData.cell === scoutCell) collectBeacon(beacon);
    beginScoutStep();
  }
}

function chooseBeaconIndices() {
  const anchors = [[.16, .22], [.81, .19], [.5, .49], [.2, .82], [.82, .8]];
  const chosen = new Set();
  return anchors.map(([ax, ay]) => {
    let best = -1, score = Infinity;
    for (let i = 0; i < data.size ** 2; i++) {
      if (!data.visible[i] || chosen.has(i)) continue;
      const x = i % data.size, y = Math.floor(i / data.size);
      const distance = (x / data.size - ax) ** 2 + (y / data.size - ay) ** 2;
      const rank = distance - data.heights[i] / 50000;
      if (rank < score) { best = i; score = rank; }
    }
    if (best !== -1) chosen.add(best);
    return best;
  }).filter(i => i !== -1);
}

function resetBeacons(previous = null) {
  for (const beacon of beacons) scene.remove(beacon);
  beacons = [];
  const oldCells = previous?.beaconCells;
  const cellsToUse = oldCells?.length && oldCells.every(i => data.visible[i]) ? oldCells : chooseBeaconIndices();
  const discovered = new Set(previous?.collectedCells || []);
  collected = 0;
  for (const [index, cell] of cellsToUse.entries()) {
    const mesh = new THREE.Mesh(beaconGeometry, beaconMaterial);
    const [x, , z] = positionOf(cell, 0);
    mesh.position.set(x, tileHeight(data.heights[cell], relief) + .75, z);
    mesh.userData = { cell, phase: index * 1.8, baseY: mesh.position.y };
    if (discovered.has(cell)) { mesh.visible = false; collected++; }
    scene.add(mesh);
    beacons.push(mesh);
  }
  $('count').textContent = `${collected} / ${beacons.length}`;
}

function saveAdventure() {
  return {
    scoutCell,
    beaconCells: beacons.map(b => b.userData.cell),
    collectedCells: beacons.filter(b => !b.visible).map(b => b.userData.cell),
  };
}

function updateUndoState() {
  $('undo-bridge').disabled = undoWorlds.length === 0;
}

function rebuildWorld(nextData, preserveAdventure = false) {
  const old = preserveAdventure ? saveAdventure() : null;
  if (!preserveAdventure) {
    undoWorlds = [];
    bridgeStart = -1;
    updateUndoState();
  }
  data = nextData;
  if (world) {
    scene.remove(world);
    world.geometry.dispose();
    world.material.dispose();
  }
  cells = [];
  for (let i = 0; i < data.size ** 2; i++) if (data.visible[i]) cells.push(i);
  world = new THREE.InstancedMesh(
    new THREE.BoxGeometry(.94, 1, .94),
    new THREE.MeshStandardMaterial({ roughness: .88, metalness: .02 }),
    cells.length,
  );
  world.name = 'ImagePixels';
  world.frustumCulled = false;
  for (let k = 0; k < cells.length; k++) world.setColorAt(k, colorHelper.setHex(data.colors[cells[k]]));
  if (world.instanceColor) world.instanceColor.needsUpdate = true;
  scene.add(world);
  activeRipples.length = 0;
  redrawTiles();
  resetBeacons(old);
  resetScout(old?.scoutCell);
}

function setBridgeMode(active) {
  bridgeMode = active;
  bridgeStart = -1;
  $('bridge').setAttribute('aria-pressed', String(active));
  $('bridge').textContent = active ? 'Bridge tool on' : 'Build a bridge';
  $('scout-status').textContent = active
    ? 'Bridge tool: tap two solid tiles, even on separate islands'
    : 'Tap terrain to send your scout on a hike';
}

function bridgeClick(tile) {
  if (!data.visible[tile]) return;
  if (bridgeStart === -1) {
    bridgeStart = tile;
    $('scout-status').textContent = 'First anchor set · tap another solid tile to build a bridge';
    return;
  }
  const from = bridgeStart;
  bridgeStart = -1;
  const next = buildBridge(data, from, tile);
  if (!next.added.length) {
    announce('This route already has solid ground. Try a wider gap.');
    return;
  }
  ++lastImport; // Any pending photo/JSON import must not overwrite edited terrain.
  undoWorlds.push(data);
  if (undoWorlds.length > 12) undoWorlds.shift();
  rebuildWorld(next.data, true);
  updateUndoState();
  showPreview(previewWorldPixels(data));
  $('source-label').textContent = 'Edited island';
  announce(`Built ${next.added.length} new bridge tile${next.added.length === 1 ? '' : 's'}.`);
  $('scout-status').textContent = 'Bridge complete · connect more islands, or switch to exploring';
}

function undoBridge() {
  if (!undoWorlds.length) return;
  ++lastImport;
  bridgeStart = -1;
  const previous = undoWorlds.pop();
  rebuildWorld(previous, true);
  updateUndoState();
  showPreview(previewWorldPixels(data));
  $('source-label').textContent = 'Edited island';
  announce('Last bridge undone.');
}

$('bridge').addEventListener('click', () => setBridgeMode(!bridgeMode));
$('undo-bridge').addEventListener('click', undoBridge);

function showPreview(rgba) {
  const ctx = $('reference').getContext('2d', { willReadFrequently: false });
  const img = new ImageData(new Uint8ClampedArray(rgba), GRID_SIZE, GRID_SIZE);
  ctx.putImageData(img, 0, 0);
}

function loadPreset() {
  const [theme, label] = themes[themeIndex];
  const rgba = demoPixels(theme);
  showPreview(rgba);
  $('source-label').textContent = label;
  rebuildWorld(voxelize(rgba));
}

$('remix').addEventListener('click', () => {
  ++lastImport; // Remix is a new world selection; invalidate stale image/JSON decodes.
  themeIndex = (themeIndex + 1) % themes.length;
  loadPreset();
  announce('New world generated. Find the glowing beacons.');
});

let lastImport = 0;
$('upload').addEventListener('change', async event => {
  const importId = ++lastImport;
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  if (!file.type.startsWith('image/') || file.size > 12 * 1024 * 1024) {
    announce('Choose an image smaller than 12 MB.');
    return;
  }
  try {
    const image = await createImageBitmap(file);
    if (importId !== lastImport) { image.close?.(); return; }
    let rgba;
    try {
      if (!image.width || !image.height || image.width * image.height > 36_000_000) {
        announce('Image dimensions too large (36 megapixels max).');
        return;
      }
      const c = document.createElement('canvas');
      c.width = c.height = GRID_SIZE;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      if (!ctx) throw new Error('2D canvas unavailable');
      const side = Math.min(image.width, image.height);
      ctx.drawImage(image, (image.width - side) / 2, (image.height - side) / 2, side, side, 0, 0, GRID_SIZE, GRID_SIZE);
      rgba = ctx.getImageData(0, 0, GRID_SIZE, GRID_SIZE).data;
    } finally {
      image.close?.();
    }
    if (importId !== lastImport) return;
    showPreview(rgba);
    $('source-label').textContent = file.name.slice(0, 42);
    rebuildWorld(voxelize(rgba));
    announce('Image remixed locally. Guide the scout across the island.');
  } catch (error) {
    if (importId !== lastImport) return;
    announce('Unable to read that image. Try a PNG or JPEG.');
    console.error('Pocket World import:', error);
  }
});

$('relief').addEventListener('input', event => {
  relief = Number(event.target.value);
  $('relief-value').textContent = relief.toFixed(1) + '×';
  redrawTiles();
  for (const beacon of beacons) {
    const cell = beacon.userData.cell;
    beacon.userData.baseY = tileHeight(data.heights[cell], relief) + .75;
  }
  if (scoutCell !== -1 && scoutDestination === -1) scoutTilePosition(scoutCell, scout.position);
  if (scoutDestination !== -1) {
    // Height changed mid-hop: continue from the visible current position.
    scoutFrom.copy(scout.position);
    scoutTilePosition(scoutDestination, scoutTo);
    scoutFraction = 0;
  }
});

$('night').addEventListener('click', event => {
  night = !night;
  event.target.setAttribute('aria-pressed', String(night));
  event.target.textContent = night ? 'Day mode' : 'Night mode';
  scene.background.setHex(night ? 0x03091d : 0x08121f);
  scene.fog.color.copy(scene.background);
  ambient.intensity = night ? 1.0 : 2.3;
  sun.intensity = night ? .6 : 3.2;
  renderer.toneMappingExposure = night ? 1.05 : 1.35;
});

$('orbit').addEventListener('click', event => {
  controls.autoRotate = !controls.autoRotate;
  event.target.textContent = controls.autoRotate ? 'Stop orbit' : 'Auto orbit';
  event.target.setAttribute('aria-pressed', String(controls.autoRotate));
});

$('reset').addEventListener('click', () => {
  camera.position.copy(HOME);
  controls.target.set(0, 0, 0);
  controls.update();
});

$('save').addEventListener('click', () => {
  const receipt = serializeWorld(data, relief);
  const url = URL.createObjectURL(new Blob([receipt], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'pocket-world.json';
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
  announce('World saved as a portable JSON receipt.');
});

$('load').addEventListener('change', async event => {
  const importId = ++lastImport; // Invalidate any older in-flight image/world import.
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  if (!/\.json$/i.test(file.name) || file.size > 128 * 1024) {
    announce('Choose a Pocket World JSON receipt under 128 KB.');
    return;
  }
  try {
    const receipt = deserializeWorld(await file.text());
    if (importId !== lastImport) return;
    relief = receipt.relief;
    $('relief').value = String(relief);
    $('relief-value').textContent = relief.toFixed(1) + '×';
    showPreview(previewWorldPixels(receipt.data));
    $('source-label').textContent = 'Restored world';
    rebuildWorld(receipt.data);
    announce('World restored locally. Explore your saved terrain.');
  } catch (error) {
    if (importId !== lastImport) return;
    announce('Invalid or unsupported Pocket World JSON.');
  }
});

$('export').addEventListener('click', () => {
  const code = exportThreeFactory(data, relief);
  const url = URL.createObjectURL(new Blob([code], { type: 'text/javascript' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'pocket-world.mjs';
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
  announce('Standalone Three.js factory exported.');
});

let down = null;
canvas.addEventListener('pointerdown', event => { down = { x: event.clientX, y: event.clientY }; });
canvas.addEventListener('pointerup', event => {
  if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 7) { down = null; return; }
  down = null;
  const rect = canvas.getBoundingClientRect();
  pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  if (bridgeMode) {
    const tileHit = world && raycaster.intersectObject(world, false)[0];
    if (tileHit?.instanceId !== undefined && cells[tileHit.instanceId] !== undefined) {
      bridgeClick(cells[tileHit.instanceId]);
    }
    return;
  }
  const hit = raycaster.intersectObjects(beacons, false)[0];
  if (hit?.object?.visible) {
    collectBeacon(hit.object);
    return;
  }
  const tile = world && raycaster.intersectObject(world, false)[0];
  if (tile?.instanceId !== undefined && cells[tile.instanceId] !== undefined) {
    const cell = cells[tile.instanceId];
    const [x, , z] = positionOf(cell, 0);
    addRipple(x, z);
    routeScout(cell);
  }
});
canvas.addEventListener('pointercancel', () => { down = null; });

function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h, false);
}
window.addEventListener('resize', resize);
resize();
loadPreset();

const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let lastFrame = 0;
let lastScoutTick = 0;
function animate(now) {
  requestAnimationFrame(animate);
  if (document.hidden) return;
  const time = now / 1000;
  const dt = lastScoutTick ? Math.min(.05, (now - lastScoutTick) / 1000) : 0;
  lastScoutTick = now;
  controls.update();
  animateScout(dt, reducedMotion);
  if (scout.visible && !reducedMotion) scoutHalo.rotation.z += dt * 1.6;
  for (const beacon of beacons) {
    if (!beacon.visible) continue;
    beacon.rotation.y += reducedMotion ? 0 : .012;
    beacon.position.y = beacon.userData.baseY + (reducedMotion ? 0 : Math.sin(time * 2.5 + beacon.userData.phase) * .16);
  }
  if (activeRipples.length) {
    for (let i = activeRipples.length - 1; i >= 0; i--) {
      if (now - activeRipples[i].born > 2400) activeRipples.splice(i, 1);
    }
    redrawTiles(now);
  }
  if (time - lastFrame > .015) {
    renderer.render(scene, camera);
    lastFrame = time;
  }
}
requestAnimationFrame(animate);
