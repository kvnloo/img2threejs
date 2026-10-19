import * as THREE from 'three';
import { createOpenFoldingCartonModel } from './factory.ts';
import { certifyFoldSweep, sampleFold } from './hinge_sweep_collision.mjs';

const root = createOpenFoldingCartonModel();
const runtime = root.userData.sculptRuntime;
const scene = new THREE.Scene();
scene.background = new THREE.Color('#808b90');
scene.add(root);
scene.add(new THREE.HemisphereLight(0xffffff, 0x736352, 2.5));
const key = new THREE.DirectionalLight(0xffffff, 2);
key.position.set(-2, 5, 4);
scene.add(key);

const cardboard = new THREE.MeshStandardMaterial({
  color: '#bf8869', roughness: 0.95, metalness: 0,
  side: THREE.DoubleSide
});
for (const mesh of Object.values(runtime.meshes)) {
  const old = mesh.material;
  mesh.material = cardboard;
  if (Array.isArray(old)) old.forEach(material => material.dispose());
  else if (old && old !== cardboard) old.dispose();
}
const width = 960, height = 760;
const renderer = new THREE.WebGLRenderer({
  antialias: true, preserveDrawingBuffer: true
});
renderer.setSize(width, height);
renderer.setPixelRatio(1);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.append(renderer.domElement);
const camera = new THREE.OrthographicCamera(-2.4, 2.4, 1.9, -1.9, 0.01, 100);
camera.position.set(0.0, 8.5, 1.9);
camera.lookAt(0, 0, 0);
const angles = {
  'back-flap': ['x', 22],
  'front-flap': ['x', -65],
  'left-flap': ['z', -24],
  'right-flap': ['z', 32],
};

function pose(kind) {
  for (const [name, entry] of Object.entries(angles)) {
    const [axis, degrees] = entry;
    const node = runtime.nodes[name];
    const hinge = runtime.hinges[name];
    hinge.rotation.y = 0;
    node.rotation.set(0, 0, 0);
    if (kind === 'hinged') hinge.rotation.y = THREE.MathUtils.degToRad(degrees);
    else if (kind === 'center-pivot') node.rotation[axis] = THREE.MathUtils.degToRad(degrees);
  }
  root.updateMatrixWorld(true);
}
function world(id, xyz) {
  return runtime.nodes[id].localToWorld(new THREE.Vector3(...xyz));
}
function seamError() {
  const joins = [
    ['back-flap', [0, 0, 0.45], [0, 0, -0.75]],
    ['front-flap', [0, 0, -0.29], [0, 0, 0.75]],
    ['left-flap', [0.42, 0, 0], [-1, 0, 0]],
    ['right-flap', [-0.44, 0, 0], [1, 0, 0]]
  ];
  const distances = joins.map(([id, onPart, onFloor]) =>
    world(id, onPart).distanceTo(world('floor', onFloor))
  );
  return { mean: distances.reduce((a, b) => a + b, 0) / distances.length,
           max: Math.max(...distances), values: distances };
}

function maskFromImageData(data, fromReference) {
  const out = new Uint8Array(width * height);
  for (let i = 0; i < out.length; i++) {
    const p = i * 4, red = data[p], green = data[p + 1], blue = data[p + 2];
    // Locked warm-cardboard vs gray-background segmentation.
    out[i] = red > 48 && red - green > 13 && red - blue > 22 ? 1 : 0;
  }
  return out;
}
function bounding(mask) {
  let x0 = width, y0 = height, x1 = -1, y1 = -1, pixels = 0;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    if (!mask[y * width + x]) continue;
    pixels++;
    x0 = Math.min(x0, x); x1 = Math.max(x1, x);
    y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  if (pixels < 1000) throw new Error('Foreground mask missing, got ' + pixels + ' pixels');
  return { x0, y0, x1, y1, pixels };
}
function normalized(mask, rect, size = 256) {
  const out = new Uint8Array(size * size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const xx = Math.min(rect.x1, Math.floor(rect.x0 + (x + 0.5) * (rect.x1 - rect.x0 + 1) / size));
    const yy = Math.min(rect.y1, Math.floor(rect.y0 + (y + 0.5) * (rect.y1 - rect.y0 + 1) / size));
    out[y * size + x] = mask[yy * width + xx];
  }
  return out;
}
function iou(a, b) {
  let both = 0, either = 0;
  for (let i = 0; i < a.length; i++) {
    if (a[i] && b[i]) both++;
    if (a[i] || b[i]) either++;
  }
  if (!either) throw new Error('Empty union');
  return Number((both / either).toFixed(6));
}

let referenceMask = null, referenceBounds = null;
async function loadReference() {
  const image = new Image();
  image.src = '/reference.jpg';
  await image.decode();
  const canvas = document.createElement('canvas');
  canvas.width = width; canvas.height = height;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.drawImage(image, 0, 0, width, height);
  referenceMask = maskFromImageData(context.getImageData(0, 0, width, height).data, true);
  referenceBounds = bounding(referenceMask);
  return referenceBounds;
}
function render(kind) {
  pose(kind);
  renderer.render(scene, camera);
  if (renderer.info.render.calls < 1 || renderer.info.render.triangles < 1) {
    throw new Error('Empty WebGL drawing for ' + kind);
  }
  const canvas = renderer.domElement;
  const context = canvas.getContext('webgl2');
  if (!context) throw new Error('WebGL2 context missing');
  // Read the actual PNG-aligned viewport into a 2D canvas via drawImage.
  const scratch = document.createElement('canvas');
  scratch.width = width; scratch.height = height;
  const ctx = scratch.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(canvas, 0, 0);
  const pixels = ctx.getImageData(0, 0, width, height).data;
  const mask = maskFromImageData(pixels, false);
  const rect = bounding(mask);
  const score = referenceMask ? iou(normalized(mask, rect), normalized(referenceMask, referenceBounds)) : null;
  const registeredScore = referenceMask ? iou(mask, referenceMask) : null;
  return {
    kind, score, registeredScore, foregroundPixels: rect.pixels, referenceForegroundPixels: referenceBounds?.pixels ?? null,
    silhouetteBounds: rect, seams: seamError(), triangles: renderer.info.render.triangles,
    rendererCalls: renderer.info.render.calls,
  };
}

/** Test the *actual emitted* procedural box, not the handcrafted OBB test. */
function testGeneratedFoldWithObstacle() {
  pose('rest');
  const flap = runtime.meshes['back-flap'];
  const joint = runtime.hinges['back-flap'];
  if (flap?.geometry?.type !== 'BoxGeometry' || !joint?.isGroup) {
    throw new Error('expected generated hinged BoxGeometry; got ' + flap?.geometry?.type);
  }
  const obstacle = new THREE.Mesh(
    new THREE.BoxGeometry(0.18, 0.18, 0.18),
    new THREE.MeshStandardMaterial({ color: '#db3d32', roughness: 0.9 }),
  );
  // Positive +X fold passes through this obstacle; the reverse path avoids it.
  obstacle.position.set(0, 0.45, -0.75);
  root.add(obstacle);
  const forwardAngles = Array.from({ length: 37 }, (_, i) => i * 5);
  const backwardAngles = Array.from({ length: 37 }, (_, i) => -i * 5);
  const sampledForward = sampleFold(joint, flap, obstacle, forwardAngles);
  const sampledBackward = sampleFold(joint, flap, obstacle, backwardAngles);
  const forward = certifyFoldSweep(joint, flap, obstacle, 0, 180);
  const backward = certifyFoldSweep(joint, flap, obstacle, 0, -180);
  const obstacleSaved = obstacle.position.clone();
  obstacle.position.set(0, 6, -0.75);
  const remote = certifyFoldSweep(joint, flap, obstacle, 0, 180);
  obstacle.position.copy(obstacleSaved);
  // Capture a frame at the colliding pose, after all numerical tests.
  joint.rotation.y = THREE.MathUtils.degToRad(90);
  root.updateMatrixWorld(true);
  renderer.render(scene, camera);
  const sampleCollision = sampledForward.samples.find(x => x.penetrating) ?? null;
  return {
    generatedComponent: 'back-flap',
    generatedGeometryType: flap.geometry.type,
    obstacleSource: 'research-only injected BoxGeometry',
    sampledPositiveCollisions: sampledForward.collisionSamples,
    sampledNegativeCollisions: sampledBackward.collisionSamples,
    firstSampledCollision: sampleCollision,
    positive: forward, negative: backward, distantObstacle: remote,
    drawCalls: renderer.info.render.calls, triangles: renderer.info.render.triangles,
  };
}


/** Adversarial collision check on every actual generated carton flap.
 * Obstacle is deliberately placed at the +90-degree panel center to
 * exercise the generated X- and Z-directed hinge frames.
 */
function testGeneratedFlapFamily() {
  const result = [];
  const ids = ['back-flap', 'front-flap', 'left-flap', 'right-flap'];
  for (const id of ids) {
    pose('rest');
    const mesh = runtime.meshes[id];
    const hinge = runtime.hinges[id];
    if (!hinge?.isGroup || mesh?.geometry?.type !== 'BoxGeometry') {
      throw new Error('missing generated box hinge: ' + id);
    }
    hinge.rotation.y = Math.PI / 2;
    root.updateMatrixWorld(true);
    const positiveCenter = mesh.getWorldPosition(new THREE.Vector3());
    hinge.rotation.y = 0;
    root.updateMatrixWorld(true);
    const obstacle = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.08, 0.08));
    obstacle.position.copy(positiveCenter);
    root.add(obstacle);
    try {
      const opening = certifyFoldSweep(hinge, mesh, obstacle, 0, 180);
      const closing = certifyFoldSweep(hinge, mesh, obstacle, 0, -180);
      const sampled = sampleFold(hinge, mesh, obstacle, [0, 45, 90, 135, 180]);
      result.push({
        id, geometry: mesh.geometry.type, hingeName: hinge.name,
        obstacle: positiveCenter.toArray(), opening, closing,
        sampledCollisions: sampled.collisionSamples,
        collisionAtNinety: sampled.samples[2].penetrating,
        initialClear: !sampled.samples[0].penetrating,
        endingClear: !sampled.samples[4].penetrating,
      });
    } finally {
      root.remove(obstacle);
      obstacle.geometry.dispose();
      obstacle.material.dispose();
      hinge.rotation.y = 0;
      root.updateMatrixWorld(true);
    }
  }
  return result;
}

window.__referenceStudy = { loadReference, render, testGeneratedFoldWithObstacle, testGeneratedFlapFamily };
window.__referenceStudyReady = true;
