#!/usr/bin/env node
/** Real Chromium + real Three.js mesh export and geometry-gate smoke.
 * Requires optional Playwright and Three.js in IMG2THREEJS_SHOWCASE_ROOT.
 * The workflow installs them outside the repository and keeps the core dep-free.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runCli, collectMeshGeometry, captureReady } from './export_mesh_geometry.mjs';

const REPO_ROOT = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const depsRoot = process.env.IMG2THREEJS_SHOWCASE_ROOT;
assert.ok(depsRoot, 'set IMG2THREEJS_SHOWCASE_ROOT to an isolated Playwright + Three.js installation');
const require = createRequire(join(resolve(depsRoot), 'package.json'));
const { chromium } = require('playwright');
const buildDir = join(resolve(depsRoot), 'node_modules', 'three', 'build');
const screenshots = join(process.env.RUNNER_TEMP || tmpdir(), 'img2-export-smoke');

function fixture(mode = 'normal') {
  return `<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#112233}</style>
<script type="module">
import * as THREE from '/three/three.module.js';
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x112233);
const modelRoot = new THREE.Group();
scene.add(modelRoot);
if (${mode === 'instances' ? 'true' : 'false'}) {
  const copies = new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1),
    new THREE.MeshBasicMaterial({color:0xffffff}), 2);
  copies.name = 'subject-copies';
  copies.setMatrixAt(0, new THREE.Matrix4().makeTranslation(0, 0, 0));
  copies.setMatrixAt(1, new THREE.Matrix4().makeTranslation(4, 0, 0));
  copies.setColorAt(0, new THREE.Color(0xff0000));
  copies.setColorAt(1, new THREE.Color(0x00ff00));
  modelRoot.add(copies);
} else {
  const geometry = new THREE.BoxGeometry(1, 1, 1);
  if (${mode === 'partial' ? 'true' : 'false'}) geometry.setDrawRange(0, 18);
  const body = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({color: 0x99cc55}));
  body.name = 'subject-box';
  body.position.set(2, 1, 0);
  body.scale.set(2, 1, 1);
  modelRoot.add(body);
}
const ground = new THREE.Mesh(new THREE.PlaneGeometry(12, 12), new THREE.MeshBasicMaterial({color: 0xff0000}));
ground.name = 'studio-ground';
scene.add(ground);
const renderer = new THREE.WebGLRenderer({antialias: false, preserveDrawingBuffer: true});
renderer.setSize(320, 240);
document.body.appendChild(renderer.domElement);
const camera = new THREE.PerspectiveCamera(50, 320/240, 0.1, 100);
camera.position.set(6, 4, 7);
camera.lookAt(2, 1, 0);
renderer.render(scene, camera);
window.__IMG2THREEJS_VIEWER__ = ${mode === 'studio-only' ? '{scene}' : '{scene, explodeRoot: modelRoot}'};
window.__IMG2THREEJS_READY__ = true;
window.__IMG2THREEJS_WEBGL_RENDERED__ = Boolean(renderer.getContext());
if (${mode === 'browser-error' ? 'true' : 'false'}) throw new Error('fixture intentional page error');
</script>`;
}

const server = createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://127.0.0.1').pathname;
  try {
    if (pathname === '/' || pathname === '/partial' || pathname === '/instances' || pathname === '/studio-only' || pathname === '/browser-error') {
      res.writeHead(200, {'content-type': 'text/html; charset=utf-8'});
      res.end(fixture(pathname.slice(1) || 'normal'));
    } else if (pathname.startsWith('/three/')) {
      const name = basename(pathname);
      if (!/^[a-zA-Z0-9._-]+\.js$/.test(name)) throw new Error('unexpected module');
      res.writeHead(200, {'content-type': 'text/javascript; charset=utf-8'});
      res.end(await readFile(join(buildDir, name)));
    } else {
      res.writeHead(404);
      res.end('Not Found');
    }
  } catch (error) {
    res.writeHead(500);
    res.end(String(error));
  }
});

await new Promise((done, reject) => {
  server.once('error', reject);
  server.listen(0, '127.0.0.1', done);
});
const address = server.address();
const url = `http://127.0.0.1:${address.port}/`;
try {
  const fs = await import('node:fs/promises');
  await fs.mkdir(screenshots, {recursive: true});

  // The public-facing CLI must drive its own real browser transport.
  const out = join(screenshots, 'meshes.json');
  assert.equal(await runCli(['--url', url, '--out', out, '--ready-flag', '__IMG2THREEJS_READY__']), 0);
  const evidence = JSON.parse(await readFile(out, 'utf8'));
  assert.equal(evidence.incomplete, false);
  assert.equal(evidence.coordinateSpace, 'world');
  assert.equal(evidence.rootSource, 'explodeRoot');
  assert.equal(evidence.sceneRootOptIn, false);
  assert.deepEqual(evidence.meshes.map(m => m.name), ['subject-box']);
  assert.equal(evidence.meshes[0].triangleCount, 12);
  assert.equal(evidence.meshes[0].indices.length, 36);
  const xs = new Set(evidence.meshes[0].vertices.map(v => v[0]));
  assert.deepEqual([...xs].sort((a,b)=>a-b), [1, 3], 'world-space translation/scale');
  assert.equal(evidence.skippedMeshes.length, 0, 'studio should be outside model root');

  // Verify the existing Python gate can consume actual browser-captured triangles.
  const gate = spawnSync('python3', ['forge/stage4_review/self_intersection.py', out, '--json'], {
    cwd: REPO_ROOT, encoding: 'utf8', maxBuffer: 4_000_000
  });
  await writeFile(join(screenshots, 'geometry-gate.stdout.json'), gate.stdout || '{}', 'utf8');
  assert.equal(gate.status, 0, `self-intersection gate failed: ${gate.stderr} ${gate.stdout}`);

  // Reproduce the original false-clean: page ready, WebGL visible and a
  // ground mesh in scene, but NO explicitly identified model root.
  const studioBrowser = await chromium.launch({headless: true});
  try {
    const page = await studioBrowser.newPage();
    await page.goto(url + 'studio-only');
    await page.waitForFunction(() => window.__IMG2THREEJS_READY__ === true);
    const ready = await page.evaluate(captureReady, {handle: '__IMG2THREEJS_VIEWER__'});
    assert.equal(ready, false, 'studio-only scene must not satisfy readiness');
    await assert.rejects(
      page.evaluate(collectMeshGeometry, {viewerHandle: '__IMG2THREEJS_VIEWER__'}),
      /explicit subject root/,
    );
    // An opt-in is for diagnostic whole-scene export, never silently selected.
    const inspection = await page.evaluate(collectMeshGeometry, {
      viewerHandle: '__IMG2THREEJS_VIEWER__', allowSceneRoot: true,
    });
    assert.equal(inspection.rootSource, 'scene-explicit');
    assert.equal(inspection.sceneRootOptIn, true);
    assert.ok(inspection.meshes.some(mesh => mesh.name === 'studio-ground'));
    await page.close();
  } finally { await studioBrowser.close(); }

  // A real InstancedMesh must expand into two complete, independently placed
  // world-space meshes with per-instance color evidence.
  const instanceOut = join(screenshots, 'instances.json');
  assert.equal(await runCli(['--url', url + 'instances', '--out', instanceOut]), 0);
  const expanded = JSON.parse(await readFile(instanceOut, 'utf8'));
  assert.equal(expanded.incomplete, false);
  assert.deepEqual(expanded.meshes.map(m => m.name), ['subject-copies[0]', 'subject-copies[1]']);
  assert.equal(expanded.meshes[0].triangleCount, 12);
  assert.equal(expanded.meshes[1].triangleCount, 12);
  const xOffsets = expanded.meshes.map(m => Math.min(...m.vertices.map(v => v[0])));
  assert.deepEqual(xOffsets, [-0.5, 3.5]);
  assert.deepEqual(expanded.meshes[0].colors.slice(0, 3), [1, 0, 0]);
  const instanceGate = spawnSync('python3',
    ['forge/stage4_review/self_intersection.py', instanceOut, '--json'],
    {cwd: REPO_ROOT, encoding: 'utf8', maxBuffer: 4_000_000});
  assert.equal(instanceGate.status, 0, `instanced geometry gate failed: ${instanceGate.stderr} ${instanceGate.stdout}`);

  // Independently prove the browser page actually rendered WebGL pixels.
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    page.on('pageerror', err => { throw err; });
    await page.goto(url);
    await page.waitForFunction(() => window.__IMG2THREEJS_READY__ && window.__IMG2THREEJS_WEBGL_RENDERED__);
    const png = join(screenshots, 'actual-webgl.png');
    await page.locator('canvas').screenshot({path: png});
    assert.ok((await stat(png)).size > 1000, 'WebGL screenshot unexpectedly small');
  } finally { await browser.close(); }

  // Fail closed even when a successful artifact existed before an incomplete run.
  const partial = await runCli(['--url', url + 'partial', '--out', out]);
  assert.equal(partial, 2);
  assert.equal(existsSync(out), false, 'stale successful mesh receipt remains');
  const diagnostic = JSON.parse(await readFile(out + '.incomplete.json', 'utf8'));
  assert.equal(diagnostic.incomplete, true);
  assert.deepEqual(diagnostic.skippedMeshes.map(m => m.reason), ['partial-draw-range']);
  // An actual Chromium uncaught exception must never leave a nominally complete
  // manifest behind, even if it occurs after a mesh was rendered and signalled ready.
  const erroredOutput = join(screenshots, 'browser-error.json');
  await writeFile(erroredOutput, 'stale manifest', 'utf8');
  assert.equal(await runCli(['--url', url + 'browser-error', '--out', erroredOutput]), 2);
  assert.equal(existsSync(erroredOutput), false);
  const exceptionReceipt = JSON.parse(await readFile(erroredOutput + '.incomplete.json', 'utf8'));
  assert.equal(exceptionReceipt.incomplete, true);
  assert.deepEqual(exceptionReceipt.browserErrors, ['fixture intentional page error']);
  assert.deepEqual(exceptionReceipt.meshes.map(m => m.name), ['subject-box']);
  console.log('PASS: real Three.js WebGL, static instances, scoped subject root, studio-only rejection, Python geometry gates, incomplete capture and script-error rejection');
} finally {
  await new Promise(resolveClose => server.close(resolveClose));
}
