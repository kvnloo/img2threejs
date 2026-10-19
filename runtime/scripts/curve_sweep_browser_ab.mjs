#!/usr/bin/env node
/** Real WebGL A/B for the #111 curve-sweep fix, not a reference-fidelity score. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, basename } from 'node:path';
const deps = process.env.IMG2THREEJS_AB_ROOT;
assert.ok(deps, 'IMG2THREEJS_AB_ROOT must point to isolated test dependencies');
const require = createRequire(join(resolve(deps), 'package.json'));
const { chromium } = require('playwright');
const { PNG } = require('pngjs');
const output = join(process.env.RUNNER_TEMP || tmpdir(), 'img2-curve-sweep-ab');
const threeBuild = join(deps, 'node_modules', 'three', 'build');

function html(variant) {
  return `<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0;background:#101418"><script type="module">
import * as THREE from '/three/three.module.js';
import * as factory from '/bundle/${variant}.js';
try {
  const model = factory.createAttachmentPrimitiveModel({textureSize: 32});
  const part = model.userData.sculptRuntime.meshes.part;
  if (!part) throw new Error('generated factory lacks the expected part');
  model.updateMatrixWorld(true);
  const geometry = part.geometry.clone();
  geometry.applyMatrix4(part.matrixWorld);
  geometry.computeBoundingBox();
  const size = new THREE.Vector3();
  geometry.boundingBox.getSize(size);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x101418);
  scene.add(new THREE.Mesh(geometry, new THREE.MeshNormalMaterial({side: THREE.DoubleSide})));
  const camera = new THREE.OrthographicCamera(-1.1, 1.1, 1.1, -1.1, 0.1, 20);
  camera.position.set(2.5, 2.2, 3.8);
  camera.lookAt(0, 0.25, 0.3);
  const renderer = new THREE.WebGLRenderer({antialias: false, preserveDrawingBuffer: true});
  renderer.setPixelRatio(1);
  renderer.setSize(512, 512);
  renderer.render(scene, camera);
  document.body.appendChild(renderer.domElement);
  window.__GEOMETRY_AB__ = {
    ready: true, type: part.geometry.type, xExtent: size.x, yExtent: size.y,
    triangles: geometry.index
      ? geometry.index.count / 3
      : geometry.attributes.position.count / 3,
    webgl: Boolean(renderer.getContext()),
  };
} catch (error) {
  window.__GEOMETRY_AB__ = {ready: false, error: String(error)};
}
</script></body></html>`;
}
const server = createServer(async (request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1');
  const path = url.pathname;
  try {
    if (path === '/before' || path === '/after') {
      response.writeHead(200, {'content-type': 'text/html; charset=utf-8'});
      response.end(html(path.substring(1)));
    } else if (path === '/three/three.module.js') {
      response.writeHead(200, {'content-type': 'text/javascript'});
      response.end(await readFile(join(threeBuild, 'three.module.js')));
    } else if (path === '/bundle/before.js' || path === '/bundle/after.js') {
      response.writeHead(200, {'content-type': 'text/javascript'});
      response.end(await readFile(join(deps, basename(path))));
    } else {
      response.writeHead(404);
      response.end('Not Found');
    }
  } catch (error) {
    response.writeHead(500);
    response.end(String(error));
  }
});
await new Promise((ok, fail) => {
  server.once('error', fail);
  server.listen(0, '127.0.0.1', ok);
});
const baseUrl = `http://127.0.0.1:${server.address().port}`;
try {
  await mkdir(output, {recursive: true});
  const browser = await chromium.launch({headless: true, args: ['--enable-webgl', '--use-gl=angle', '--use-angle=swiftshader']});
  const reports = {};
  const screenshots = {};
  try {
    for (const name of ['before', 'after']) {
      const page = await browser.newPage({viewport: {width: 512, height: 512}, deviceScaleFactor: 1});
      const errors = [];
      page.on('pageerror', error => errors.push(String(error)));
      await page.goto(`${baseUrl}/${name}`);
      await page.waitForFunction(() => window.__GEOMETRY_AB__ !== undefined);
      const report = await page.evaluate(() => window.__GEOMETRY_AB__);
      assert.equal(report.ready, true, JSON.stringify({name, errors, report}));
      assert.equal(report.webgl, true);
      assert.deepEqual(errors, [], 'browser JavaScript errors');
      assert.ok(report.triangles > 10, 'emitted geometry has triangles');
      reports[name] = report;
      const png = await page.locator('canvas').screenshot({path: join(output, `${name}.png`)});
      screenshots[name] = png;
      await page.close();
    }
  } finally {
    await browser.close();
  }
  assert.equal(reports.before.type, 'CylinderGeometry', 'baseline should exhibit #111');
  assert.equal(reports.after.type, 'ExtrudeGeometry', 'patch must render authored curveSweep');
  assert.ok(reports.after.xExtent > reports.before.xExtent * 2.0,
    `the authored hook must have a wider geometric extent: ${JSON.stringify(reports)}`);
  const before = PNG.sync.read(screenshots.before);
  const after = PNG.sync.read(screenshots.after);
  assert.equal(before.width, after.width);
  assert.equal(before.height, after.height);
  let changed = 0, beforeVisible = 0, afterVisible = 0;
  // Compare the exact same fixed-camera WebGL pixels, not independent auto-framings.
  for (let i = 0; i < before.data.length; i += 4) {
    const delta = Math.abs(before.data[i] - after.data[i])
      + Math.abs(before.data[i + 1] - after.data[i + 1])
      + Math.abs(before.data[i + 2] - after.data[i + 2]);
    if (delta >= 40) changed++;
    if (before.data[i] + before.data[i+1] + before.data[i+2] > 100) beforeVisible++;
    if (after.data[i] + after.data[i+1] + after.data[i+2] > 100) afterVisible++;
  }
  assert.ok(changed > 500, `rendered A/B too similar (${changed} changed pixels)`);
  assert.ok(beforeVisible > 400 && afterVisible > 400,
    `invisible geometry in one render: before=${beforeVisible} after=${afterVisible}`);
  const report = {
    kind: 'generated-factory-real-webgl-ab',
    issue: 'img2threejs/img2threejs#111',
    sameAuthoredSpec: true,
    fixedCamera: true,
    baseline: reports.before,
    patch: reports.after,
    changedPixels: changed,
    beforeVisible, afterVisible,
    beforeSha256: createHash('sha256').update(screenshots.before).digest('hex'),
    afterSha256: createHash('sha256').update(screenshots.after).digest('hex'),
    comparisonToUserReference: false,
    qualityScore: null,
    note: 'Actual WebGL geometry/path A/B. No reference-image IoU, likeness, or real-subject fidelity claim.',
  };
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n', 'utf8');
  console.log('PASS: generated-factory real-browser A/B ' + JSON.stringify(report));
} finally {
  await new Promise(done => server.close(done));
}
