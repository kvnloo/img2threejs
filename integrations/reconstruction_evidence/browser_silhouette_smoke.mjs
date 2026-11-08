#!/usr/bin/env node
/** Real Chromium + Three.js synthetic-oracle control for evidence silhouette A/B.
 * This validates actual WebGL pixels and objective wiring; it is NOT a photo
 * reconstruction, DA3 inference run, or production fidelity claim.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const ROOT = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const dependencyRoot = process.env.IMG2THREEJS_BROWSER_DEPS;
assert.ok(dependencyRoot, 'set IMG2THREEJS_BROWSER_DEPS to isolated installed playwright + three');
const require = createRequire(join(resolve(dependencyRoot), 'package.json'));
const { chromium } = require('playwright');
const threeBuild = join(resolve(dependencyRoot), 'node_modules', 'three', 'build');
const outDir = process.env.IMG2THREEJS_EVIDENCE_OUT
  || await mkdtemp(join(tmpdir(), 'img2-evidence-webgl-'));
await mkdir(outDir, {recursive: true});

function pageHtml(variant) {
  const offset = variant === 'shifted' ? 0.65 : 0;
  return `<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:transparent}canvas{display:block}</style>
</head><body><script type="module">
import * as THREE from '/three/three.module.js';
const renderer = new THREE.WebGLRenderer({alpha:true, antialias:false, preserveDrawingBuffer:true});
renderer.setSize(224, 224, false);
renderer.setPixelRatio(1);
renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const shape = new THREE.Group();
const main = new THREE.Mesh(
  new THREE.BoxGeometry(1.4, 1.05, 0.8),
  new THREE.MeshBasicMaterial({color:0x69d4aa})
);
const cap = new THREE.Mesh(
  new THREE.SphereGeometry(0.32, 24, 16),
  new THREE.MeshBasicMaterial({color:0xdab66c})
);
cap.position.set(0.36, 0.55, 0.1);
shape.add(main, cap);
shape.position.x = ${offset};
scene.add(shape);
const camera = new THREE.OrthographicCamera(-1.7, 1.7, 1.7, -1.7, 0.1, 30);
camera.position.set(4.5, 3.1, 5.2);
camera.lookAt(0,0,0);
renderer.render(scene, camera);
window.__IMG2_SMOKE_WEBGL__ = Boolean(renderer.getContext());
window.__IMG2_SMOKE_READY__ = true;
</script></body></html>`;
}

const server = createServer(async (req, res) => {
  try {
    const path = new URL(req.url, 'http://127.0.0.1').pathname;
    if (path === '/reference' || path === '/matching' || path === '/shifted') {
      res.writeHead(200, {'content-type':'text/html; charset=utf-8'});
      res.end(pageHtml(path.substring(1)));
    } else if (path.startsWith('/three/')) {
      const file = basename(path);
      if (file !== 'three.module.js') throw new Error('unexpected module request');
      res.writeHead(200, {'content-type':'text/javascript; charset=utf-8'});
      res.end(await readFile(join(threeBuild, file)));
    } else {
      res.writeHead(404);res.end('Not Found');
    }
  } catch (error) {
    res.writeHead(500);res.end(String(error));
  }
});
await new Promise((done, reject) => {
  server.once('error', reject);
  server.listen(0, '127.0.0.1', done);
});
const url = `http://127.0.0.1:${server.address().port}`;
const digests = {};
try {
  const browser = await chromium.launch({headless:true});
  try {
    const context = await browser.newContext({viewport:{width:224,height:224}, deviceScaleFactor:1});
    for (const variant of ['reference', 'matching', 'shifted']) {
      const page = await context.newPage();
      const failures = [];
      page.on('pageerror', error => failures.push(String(error)));
      await page.goto(url + '/' + variant, {waitUntil:'domcontentloaded', timeout:20000});
      await page.waitForFunction(() => window.__IMG2_SMOKE_READY__ === true
        && window.__IMG2_SMOKE_WEBGL__ === true, {timeout:20000});
      assert.deepEqual(failures, [], `browser exceptions during ${variant}`);
      const dataUri = await page.evaluate(() => {
        const canvas = document.querySelector('canvas');
        if (!canvas || canvas.width !== 224 || canvas.height !== 224)
          throw new Error('expected 224x224 renderer canvas');
        return canvas.toDataURL('image/png');
      });
      assert.ok(dataUri.startsWith('data:image/png;base64,'), 'WebGL PNG unavailable');
      const png = Buffer.from(dataUri.slice('data:image/png;base64,'.length), 'base64');
      assert.ok(png.length > 500, 'WebGL pixels missing');
      const path = join(outDir, `${variant}.png`);
      await writeFile(path, png);
      digests[variant] = createHash('sha256').update(png).digest('hex');
      await page.close();
    }
    await context.close();
  } finally {
    await browser.close();
  }

  assert.equal(digests.reference, digests.matching, 'same WebGL scene produced different pixels');
  assert.notEqual(digests.reference, digests.shifted, 'shifted scene unexpectedly identical');
  const reportPath = join(outDir, 'silhouette-actual-webgl.json');
  const program = join(ROOT, 'integrations/reconstruction_evidence/evaluate_browser_silhouette.py');
  const result = spawnSync('python3', [
    program,
    '--reference-render', join(outDir, 'reference.png'),
    '--matching-render', join(outDir, 'matching.png'),
    '--shifted-render', join(outDir, 'shifted.png'),
    '--out', reportPath,
  ], {cwd:ROOT, encoding:'utf8', maxBuffer:6_000_000});
  assert.equal(result.status, 0, `Python silhouette/evidence gate: ${result.stdout}\n${result.stderr}`);
  const report = JSON.parse(await readFile(reportPath, 'utf8'));
  assert.equal(report.fixtureClass, 'synthetic-controlled-webgl-reference');
  assert.equal(report.shadowParity, true);
  assert.ok(report.matchingIoU >= 0.98, 'matching scene unexpectedly low silhouette IoU');
  assert.ok(report.shiftedIoU <= report.matchingIoU - 0.05,
    'silhouette critic missed a known wrong-position defect');
  assert.equal(report.evaluationsPerArm, 3);
  assert.ok(report.experimentalSelectedBetterCandidate);
  console.log(JSON.stringify({
    verdict:'PASS', outDir, matchingIoU:report.matchingIoU,
    shiftedIoU:report.shiftedIoU, evaluationsPerArm:report.evaluationsPerArm,
    shadowParity:report.shadowParity,
  }));
} finally {
  await new Promise(done => server.close(done));
}
