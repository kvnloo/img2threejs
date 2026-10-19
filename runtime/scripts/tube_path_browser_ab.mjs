#!/usr/bin/env node
/** Real WebGL A/B for the #111 tube-path fix, not a reference-fidelity score. */
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
const output = join(process.env.RUNNER_TEMP || tmpdir(), 'img2-tube-path-ab');
const threeBuild = join(deps, 'node_modules', 'three', 'build');

function geometryScript(variant) {
  if (variant === 'reference') {
    // This third render is an independently authored Three.js realization
    // of the exact *fixture spec*. It is not a user-supplied reference photo.
    return `
  const spec = await (await fetch('/fixture.json')).json();
  const part = spec.componentTree.find(entry => entry.id === 'part');
  const parent = spec.componentTree.find(entry => entry.id === part.parent);
  const sweep = part.geometryDescriptor.tubePath;
  const spine = sweep.points.map(v => new THREE.Vector3(...v));
  const path = new THREE.CatmullRomCurve3(spine, sweep.closed === true);
  const geometry = new THREE.TubeGeometry(
    path, Math.max(8, spine.length * 6),
    sweep.radius ?? 0.05, sweep.radialSegments ?? 8, sweep.closed ?? false,
  );
  geometry.scale(part.dimensions.width, part.dimensions.height, part.dimensions.depth);
  geometry.translate(
    parent.transform.position[0] + part.transform.position[0],
    parent.transform.position[1] + part.transform.position[1],
    parent.transform.position[2] + part.transform.position[2],
  );
  const type = geometry.type;
`;
  }
  return `
  const model = factory.createAttachmentPrimitiveModel({textureSize: 32});
  const part = model.userData.sculptRuntime.meshes.part;
  if (!part) throw new Error('generated factory lacks the expected part');
  model.updateMatrixWorld(true);
  const geometry = part.geometry.clone();
  geometry.applyMatrix4(part.matrixWorld);
  const type = part.geometry.type;
`;
}

function html(variant) {
  return `<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0;background:#101418"><script type="module">
import * as THREE from '/three/three.module.js';
${variant === 'reference' ? '' : `import * as factory from '/bundle/${variant}.js';`}
try {
${geometryScript(variant)}
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
    ready: true, type, xExtent: size.x, yExtent: size.y,
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
    if (path === '/before' || path === '/after' || path === '/reference') {
      response.writeHead(200, {'content-type': 'text/html; charset=utf-8'});
      response.end(html(path.substring(1)));
    } else if (path === '/three/three.module.js') {
      response.writeHead(200, {'content-type': 'text/javascript'});
      response.end(await readFile(join(threeBuild, 'three.module.js')));
    } else if (path === '/fixture.json') {
      response.writeHead(200, {'content-type': 'application/json'});
      response.end(await readFile(join(deps, 'fixture.json')));
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
    for (const name of ['before', 'after', 'reference']) {
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
  assert.equal(reports.after.type, 'TubeGeometry', 'patch must render authored tubePath');
  assert.ok(reports.after.xExtent > reports.before.xExtent * 2.0,
    `the authored hook must have a wider curved-tube geometric extent: ${JSON.stringify(reports)}`);
  const before = PNG.sync.read(screenshots.before);
  const after = PNG.sync.read(screenshots.after);
  const reference = PNG.sync.read(screenshots.reference);
  assert.equal(reports.reference.type, 'TubeGeometry', 'independent controlled target');
  assert.ok(Math.abs(reports.reference.xExtent - reports.after.xExtent) < 1e-4,
    'generated width must match the authored procedural target');
  assert.equal(before.width, after.width);
  assert.equal(after.width, reference.width);
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
  const visible = (png, i) => png.data[i] + png.data[i+1] + png.data[i+2] > 100;
  const silhouetteIoU = (observed, target) => {
    let intersection = 0, union = 0, seen = 0;
    for (let i = 0; i < observed.data.length; i += 4) {
      const actual = visible(observed, i);
      const intended = visible(target, i);
      if (actual && intended) intersection++;
      if (actual || intended) union++;
      if (intended) seen++;
    }
    assert.ok(seen > 400 && union > 400, 'synthetic target has no usable silhouette');
    return {iou: intersection / union, intersectionPixels: intersection, unionPixels: union};
  };
  const silhouetteBefore = silhouetteIoU(before, reference);
  const silhouetteAfter = silhouetteIoU(after, reference);
  assert.ok(silhouetteAfter.iou >= 0.97,
    `the patch must reproduce the controlled curved target: ${JSON.stringify(silhouetteAfter)}`);
  assert.ok(silhouetteAfter.iou >= silhouetteBefore.iou + 0.3,
    `the patch must improve the controlled target by >=0.3 IoU: ${JSON.stringify({silhouetteBefore, silhouetteAfter})}`);
  const report = {
    kind: 'generated-factory-real-webgl-ab',
    issue: 'img2threejs/img2threejs#91',
    sameAuthoredSpec: true,
    fixedCamera: true,
    baseline: reports.before,
    patch: reports.after,
    changedPixels: changed,
    beforeVisible, afterVisible,
    controlledProceduralReference: {
      geometry: reports.reference,
      provenance: 'independently built from fixture.json using Three.js CatmullRom + TubeGeometry',
      silhouetteBefore, silhouetteAfter,
      referenceScreenshotSha256: createHash('sha256').update(screenshots.reference).digest('hex'),
    },
    beforeSha256: createHash('sha256').update(screenshots.before).digest('hex'),
    afterSha256: createHash('sha256').update(screenshots.after).digest('hex'),
    comparisonToUserReference: false,
    qualityScore: null,
    note: 'Real WebGL geometry A/B; silhouette IoU is against a separate controlled procedural fixture, NOT against a user/reference photograph or actual subject.',
  };
  await writeFile(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n', 'utf8');
  console.log('PASS: generated-factory real-browser tube-path A/B ' + JSON.stringify(report));
} finally {
  await new Promise(done => server.close(done));
}
