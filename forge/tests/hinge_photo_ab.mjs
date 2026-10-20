#!/usr/bin/env node
/** Research-only real-photo A/B using emitted Three.js, fixed authored setup. */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { chromium } from 'playwright';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const work = mkdtempSync(join(root, '.hinge-photo-ab-'));
const reference = process.env.HINGE_REFERENCE_PHOTO;
if (!reference) throw new Error('HINGE_REFERENCE_PHOTO is required');
const output = process.env.HINGE_AB_OUTPUT || join(work, 'out');
mkdirSync(output, { recursive: true });
const photo = readFileSync(reference);
if (photo.length < 25000 || photo[0] !== 0xff || photo[1] !== 0xd8) {
  throw new Error('Reference photo must be the actual nonempty JPEG');
}
const digest = createHash('sha256').update(photo).digest('hex');
const credit = 'Arnold Reinhold / Wikimedia Commons / CC BY-SA 3.0';
const license = 'https://creativecommons.org/licenses/by-sa/3.0/';
const source = 'https://commons.wikimedia.org/wiki/File:Box.agr.jpg';
let browser, server;
try {
  execFileSync('python3', [join(root, 'forge/tests/emit_hinge_photo_fixture.py'),
    join(work, 'factory.ts')], { cwd: root, stdio: 'inherit' });
  execFileSync(join(root, 'node_modules/.bin/tsc'), [
    '--noEmit', '--strict', '--skipLibCheck', '--target', 'es2022',
    '--module', 'esnext', '--moduleResolution', 'bundler',
    '--lib', 'es2022,dom', join(work, 'factory.ts'),
  ], { cwd: root, stdio: 'inherit' });
  writeFileSync(join(work, 'client.mjs'),
    readFileSync(join(root, 'forge/tests/hinge_photo_client.mjs'), 'utf8'));
  writeFileSync(join(work, 'hinge_sweep_collision.mjs'),
    readFileSync(join(root, 'forge/tests/hinge_sweep_collision.mjs'), 'utf8'));
  writeFileSync(join(work, 'hinge_photo_frame_fit.mjs'),
    readFileSync(join(root, 'forge/tests/hinge_photo_frame_fit.mjs'), 'utf8'));
  await build({
    entryPoints: [join(work, 'client.mjs')], outfile: join(work, 'bundle.js'),
    bundle: true, platform: 'browser', format: 'esm', logLevel: 'warning',
  });
  writeFileSync(join(work, 'index.html'), '<!doctype html><html><head>' +
    '<meta charset="utf-8"><style>body{margin:0;background:#808b90}' +
    'canvas{display:block}</style></head><body>' +
    '<script type="module" src="/bundle.js"></script></body></html>');
  server = createServer((req, res) => {
    const files = {
      '/': [join(work, 'index.html'), 'text/html'],
      '/index.html': [join(work, 'index.html'), 'text/html'],
      '/bundle.js': [join(work, 'bundle.js'), 'text/javascript'],
      '/reference.jpg': [reference, 'image/jpeg'],
      '/hinged.png': [join(output, 'hinged.png'), 'image/png'],
      '/center-pivot.png': [join(output, 'center-pivot.png'), 'image/png'],
    };
    const resource = files[req.url || '/'];
    if (!resource) return res.writeHead(404).end();
    res.writeHead(200, { 'Content-Type': resource[1] });
    res.end(readFileSync(resource[0]));
  });
  await new Promise((ok, fail) => server.once('error', fail).listen(0, '127.0.0.1', ok));
  const url = 'http://127.0.0.1:' + server.address().port;
  browser = await chromium.launch({
    headless: true,
    args: ['--use-gl=angle', '--use-angle=swiftshader',
           '--enable-webgl', '--ignore-gpu-blocklist', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage({viewport: {width: 960, height: 760},deviceScaleFactor:1});
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));
  await page.goto(url, { waitUntil: 'load' });
  await page.waitForFunction(() => window.__referenceStudyReady === true, null, {timeout:45000});
  const photoMask = await page.evaluate(() => window.__referenceStudy.loadReference());
  const measurements = [];
  for (const kind of ['hinged', 'center-pivot']) {
    const measurement = await page.evaluate(k => window.__referenceStudy.render(k), kind);
    assert.ok(Number.isFinite(measurement.score));
    assert.ok(Number.isFinite(measurement.registeredScore));
    assert.ok(measurement.rendererCalls > 0 && measurement.triangles > 0);
    await page.locator('canvas').screenshot({ path: join(output, kind + '.png') });
    measurements.push(measurement);
  }
  assert.ok(measurements[0].seams.max < 0.0001, 'Correct hinge must keep all four seams attached');
  assert.ok(measurements[1].seams.max > 0.01, 'Center-pivot counterfactual must show displaced seams');
  assert.deepEqual(errors, [], 'browser errors');
  const framing = [];
  for (const kind of ['hinged', 'center-pivot']) {
    const found = await page.evaluate(k => window.__referenceStudy.fitCamera(k), kind);
    assert.equal(found.kind, kind);
    assert.equal(found.attempts, 12);
    assert.ok(found.evaluations <= found.budget, 'bounded camera search budget');
    assert.ok(found.fittedMetrics.train + 1e-6 >= found.baseline.train);
    assert.ok(Number.isFinite(found.fittedMetrics.holdout));
    framing.push(found);
    await page.evaluate(({kind,fitted})=>{
      window.__referenceStudy.applyFrame(fitted);
      window.__referenceStudy.render(kind);
    }, found);
    await page.locator('canvas').screenshot({
      path: join(output, 'fitted-' + kind + '.png')
    });
    await page.evaluate(() => window.__referenceStudy.resetFrame());
  }
  assert.deepEqual(errors, [], 'browser errors after deterministic camera fit');
  console.log('HINGE_CAMERA_FIT:', JSON.stringify(framing.map(x=>({
    kind:x.kind, initial:x.baseline, fitted:x.fittedMetrics,
    params:x.fitted, evaluations:x.evaluations, budget:x.budget
  }))));
  const generatedSweep = await page.evaluate(() =>
    window.__referenceStudy.testGeneratedFoldWithObstacle());
  assert.equal(generatedSweep.generatedGeometryType, 'BoxGeometry');
  assert.ok(generatedSweep.sampledPositiveCollisions > 0,
    'actual generated panel must encounter the obstacle');
  assert.equal(generatedSweep.sampledNegativeCollisions, 0);
  assert.equal(generatedSweep.positive.status, 'collision');
  assert.equal(generatedSweep.negative.status, 'certified-clear');
  assert.equal(generatedSweep.distantObstacle.status, 'certified-clear');
  assert.ok(generatedSweep.drawCalls > 0 && generatedSweep.triangles > 0);
  assert.deepEqual(errors, [], 'browser errors from collision validation');
  await page.locator('canvas').screenshot({
    path: join(output, 'generated-sweep-collision.png')
  });
  const oblique = await page.evaluate(() =>
    window.__referenceStudy.renderObliqueCollision());
  assert.ok(oblique.drawCalls > 0 && oblique.triangles > 0);
  await page.locator('canvas').screenshot({
    path: join(output, 'generated-sweep-oblique.png')
  });
  const generatedFlaps = await page.evaluate(() =>
    window.__referenceStudy.testGeneratedFlapFamily());
  assert.equal(generatedFlaps.length, 4);
  for (const flap of generatedFlaps) {
    assert.equal(flap.geometry, 'BoxGeometry', flap.id);
    assert.equal(flap.initialClear, true, flap.id + ' start collision');
    assert.equal(flap.endingClear, true, flap.id + ' end collision');
    assert.equal(flap.collisionAtNinety, true, flap.id + ' midpoint missed');
    assert.equal(flap.opening.status, 'collision', flap.id);
    assert.equal(flap.closing.status, 'certified-clear', flap.id + ' reverse');
    assert.ok(['collision', 'certified-clear', 'unresolved'].includes(flap.floorSweep.status),
      'actual floor fold must have a documented tri-state verdict');
  }
  console.log('HINGE_GENERATED_FLAP_FAMILY:', JSON.stringify(generatedFlaps));
  const comparisonPage = await browser.newPage({ viewport: {width: 1500, height: 600},deviceScaleFactor:1 });
  const columns = [
    ['Reference photo', 'reference.jpg'],
    ['Correct edge pivots', 'hinged.png'],
    ['Incorrect center pivots', 'center-pivot.png'],
  ].map(entry => '<section><h3>' + entry[0] + '</h3><img src="/' + entry[1] + '"></section>').join('');
  const style = '<style>body{font:16px system-ui;margin:15px;color:#15202b;background:#f8f9fb}' +
    'main{display:flex;gap:14px}section{width:480px}section img{width:480px;height:380px;object-fit:contain;' +
    'background:#808b90}small{font-size:13px;color:#4b5563}</style>';
  await comparisonPage.goto(url);
  await comparisonPage.setContent('<!doctype html><html><head>' + style + '</head><body><main>' +
    columns + '</main><p><small>' + credit + '. Source: ' + source +
    ' (crop/rescale for comparison; no reconstructed textures). ' +
    'Manually authored proxy; not automated 3D reconstruction.</small></p></body></html>',
    {waitUntil:'load'});
  await comparisonPage.evaluate(() => Promise.all([...document.images].map(img => img.decode())));
  await comparisonPage.screenshot({ path: join(output, 'photo-ab-comparison.png'), fullPage: true });

  const summary = {
    source, creator: 'Arnold Reinhold', license, credit,
    sha256: digest, photoMask, baseline: measurements[1], hinge: measurements[0],
    generatedSweep, generatedFlaps, oblique, framing,
    normalizedIoUDelta: Number((measurements[0].score - measurements[1].score).toFixed(6)),
    fixedFrameIoUDelta: Number((measurements[0].registeredScore - measurements[1].registeredScore).toFixed(6)),
    methodology: 'manual proxy, fixed camera/lighting/angles, warm-cardboard vs gray mask; record both original fixed-frame 960x760 IoU and independently bbox-normalized 256x256 silhouette IoU',
    limitations: ['single 2005 reference photograph', 'not automatic image reconstruction',
      'box walls, corrugation, perspective, lighting and crop not optimized',
      'normalized IoU discards absolute framing/scale',
      'seam geometry is a designed fixture; no arbitrary collision guarantees'],
  };
  writeFileSync(join(output, 'measurements.json'), JSON.stringify(summary, null, 2) + '\n');
  console.log('HINGE_GENERATED_SWEEP:', JSON.stringify(generatedSweep));
  console.log('HINGE_PHOTO_AB:', JSON.stringify({
    source, baselineNormalizedIoU: summary.baseline.score,
    hingeNormalizedIoU: summary.hinge.score, delta: summary.normalizedIoUDelta,
    baselineFixedFrameIoU: summary.baseline.registeredScore,
    hingeFixedFrameIoU: summary.hinge.registeredScore, fixedFrameDelta: summary.fixedFrameIoUDelta,
    baselineSeamMax: summary.baseline.seams.max,
    hingeSeamMax: summary.hinge.seams.max, sha256: digest,
  }));
} finally {
  if (browser) await browser.close();
  if (server) await new Promise(resolve => server.close(resolve));
  rmSync(work, {recursive:true,force:true});
}
