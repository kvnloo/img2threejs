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
import { runCli } from './export_mesh_geometry.mjs';

const REPO_ROOT = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const depsRoot = process.env.IMG2THREEJS_SHOWCASE_ROOT;
assert.ok(depsRoot, 'set IMG2THREEJS_SHOWCASE_ROOT to an isolated Playwright + Three.js installation');
const require = createRequire(join(resolve(depsRoot), 'package.json'));
const { chromium } = require('playwright');
const buildDir = join(resolve(depsRoot), 'node_modules', 'three', 'build');
const screenshots = join(process.env.RUNNER_TEMP || tmpdir(), 'img2-export-smoke');

function fixture(partial = false) {
  return `<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#112233}</style>
<script type="module">
import * as THREE from '/three/three.module.js';
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x112233);
const modelRoot = new THREE.Group();
scene.add(modelRoot);
const geometry = new THREE.BoxGeometry(1, 1, 1);
if (${partial ? 'true' : 'false'}) geometry.setDrawRange(0, 18);
const body = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({color: 0x99cc55}));
body.name = 'subject-box';
body.position.set(2, 1, 0);
body.scale.set(2, 1, 1);
modelRoot.add(body);
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
window.__IMG2THREEJS_VIEWER__ = {scene, explodeRoot: modelRoot};
window.__IMG2THREEJS_READY__ = true;
window.__IMG2THREEJS_WEBGL_RENDERED__ = Boolean(renderer.getContext());
</script>`;
}

const server = createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://127.0.0.1').pathname;
  try {
    if (pathname === '/' || pathname === '/partial') {
      res.writeHead(200, {'content-type': 'text/html; charset=utf-8'});
      res.end(fixture(pathname === '/partial'));
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
  console.log('PASS: real Three.js WebGL + browser exporter + Python geometry gate; incomplete capture rejected');
} finally {
  await new Promise(resolveClose => server.close(resolveClose));
}
