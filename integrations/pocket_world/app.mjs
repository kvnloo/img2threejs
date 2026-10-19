import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GRID_SIZE, demoPixels, voxelize, tileHeight, exportThreeFactory } from './world-data.mjs';

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

function resetBeacons() {
  for (const beacon of beacons) scene.remove(beacon);
  beacons = [];
  collected = 0;
  for (const [index, cell] of chooseBeaconIndices().entries()) {
    const mesh = new THREE.Mesh(beaconGeometry, beaconMaterial);
    const [x, , z] = positionOf(cell, 0);
    mesh.position.set(x, tileHeight(data.heights[cell], relief) + .75, z);
    mesh.userData = { cell, phase: index * 1.8, baseY: mesh.position.y };
    scene.add(mesh);
    beacons.push(mesh);
  }
  $('count').textContent = `0 / ${beacons.length}`;
}

function rebuildWorld(nextData) {
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
  resetBeacons();
}

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
  themeIndex = (themeIndex + 1) % themes.length;
  loadPreset();
  announce('New world generated. Find the glowing beacons.');
});

$('upload').addEventListener('change', async event => {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  if (!file.type.startsWith('image/') || file.size > 12 * 1024 * 1024) {
    announce('Choose an image smaller than 12 MB.');
    return;
  }
  try {
    const image = await createImageBitmap(file);
    const c = document.createElement('canvas');
    c.width = c.height = GRID_SIZE;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    const side = Math.min(image.width, image.height);
    ctx.clearRect(0, 0, GRID_SIZE, GRID_SIZE);
    ctx.drawImage(image, (image.width - side) / 2, (image.height - side) / 2, side, side, 0, 0, GRID_SIZE, GRID_SIZE);
    image.close?.();
    const rgba = ctx.getImageData(0, 0, GRID_SIZE, GRID_SIZE).data;
    showPreview(rgba);
    $('source-label').textContent = file.name.slice(0, 42);
    rebuildWorld(voxelize(rgba));
    announce('Image remixed locally. Find the five beacons.');
  } catch (error) {
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
  const hit = raycaster.intersectObjects(beacons, false)[0];
  if (hit?.object?.visible) {
    hit.object.visible = false;
    collected++;
    $('count').textContent = `${collected} / ${beacons.length}`;
    activeRipples.push({ x: hit.object.position.x, z: hit.object.position.z, born: performance.now() });
    announce(collected === beacons.length ? 'World complete! Remix to explore another island.' : `${collected} beacon${collected === 1 ? '' : 's'} discovered.`);
    return;
  }
  const tile = world && raycaster.intersectObject(world, false)[0];
  if (tile?.instanceId !== undefined) {
    const [x, , z] = positionOf(cells[tile.instanceId], 0);
    activeRipples.push({ x, z, born: performance.now() });
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
function animate(now) {
  requestAnimationFrame(animate);
  if (document.hidden) return;
  const time = now / 1000;
  controls.update();
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
