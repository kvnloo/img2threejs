#!/usr/bin/env node
/** Optional real Three.js + Chromium smoke for Pocket World.
 * Dependencies are installed in an isolated temporary folder by GitHub Actions.
 * This never downloads meshes/images and does not change core forge dependencies.
 */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const depsRoot = process.env.IMG2THREEJS_BROWSER_DEPS_ROOT;
assert.ok(depsRoot, 'set IMG2THREEJS_BROWSER_DEPS_ROOT to isolated playwright/three/esbuild installation');
const require = createRequire(join(resolve(depsRoot), 'package.json'));
const { chromium } = require('playwright');
const { build } = require('esbuild');
const threeRoot = join(resolve(depsRoot), 'node_modules', 'three');
const threePackage = JSON.parse(await readFile(join(threeRoot, 'package.json'), 'utf8'));
assert.equal(threePackage.version, '0.169.0', 'browser smoke must match pinned Three.js r169');
const bundlePath = join(resolve(depsRoot), 'pocket-world-real-webgl.js');
await build({
  entryPoints: [join(ROOT, 'app.mjs')],
  outfile: bundlePath,
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: ['es2020'],
  logLevel: 'warning',
  plugins: [{
    name: 'pinned-three',
    setup(bundler) {
      bundler.onResolve({ filter: /^three$/ }, () => ({ path: join(threeRoot, 'build', 'three.module.js') }));
      bundler.onResolve({ filter: /^three\/addons\// }, args => ({
        path: join(threeRoot, 'examples', 'jsm', args.path.slice('three/addons/'.length)),
      }));
    },
  }],
});

const html = (await readFile(join(ROOT, 'index.html'), 'utf8'))
  .replace(/<script type="importmap">[\s\S]*?<\/script>/, '')
  .replace('<script type="module" src="./app.mjs"></script>', '<script src="/app.bundle.js"></script>');
assert.ok(html.includes('<script src="/app.bundle.js"></script>'), 'failed to mount bundled app');
const bundle = await readFile(bundlePath);
const server = createServer((request, response) => {
  const pathname = new URL(request.url, 'http://127.0.0.1').pathname;
  if (pathname === '/') {
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    response.end(html);
  } else if (pathname === '/app.bundle.js') {
    response.writeHead(200, { 'content-type': 'text/javascript; charset=utf-8' });
    response.end(bundle);
  } else {
    response.writeHead(404);
    response.end('Not found');
  }
});
await new Promise((ok, fail) => { server.once('error', fail); server.listen(0, '127.0.0.1', ok); });
const url = `http://127.0.0.1:${server.address().port}/`;
let browser;
try {
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({viewport: {width: 1100, height: 740}, acceptDownloads: true});
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.goto(url, {waitUntil:'domcontentloaded'});
  await page.locator('#viewport').waitFor();
  await page.waitForFunction(() => document.querySelector('#count')?.textContent?.includes(' / 5'));
  await page.waitForTimeout(700);
  const webgl = await page.evaluate(() => {
    const canvas = document.getElementById('viewport');
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    return gl ? {version: String(gl.getParameter(gl.VERSION)), width: canvas.width, height: canvas.height} : null;
  });
  assert.ok(webgl && webgl.width >= 900 && webgl.height >= 500, 'real WebGL viewport did not initialize');
  const shotDir = join(process.env.RUNNER_TEMP || resolve(depsRoot), 'pocket-world-webgl-smoke');
  await mkdir(shotDir, { recursive: true });
  const screenshot = await page.locator('#viewport').screenshot({path:join(shotDir, 'world-day.png')});
  assert.ok(screenshot.length > 4000, 'World screenshot unexpectedly tiny');
  // WebGL context existing is not enough; prove actual brightly colored world pixels.
  const visible = await page.evaluate(async base64 => {
    const img = new Image();
    img.src = 'data:image/png;base64,' + base64;
    await img.decode();
    const cvs = document.createElement('canvas');
    cvs.width = img.width; cvs.height = img.height;
    const ctx = cvs.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const rgba = ctx.getImageData(0, 0, img.width, img.height).data;
    let bright = 0;
    for (let i = 0; i < rgba.length; i += 4) {
      if (rgba[i] > 85 && rgba[i] > rgba[i + 2] * 1.2 && rgba[i + 1] > 40) bright++;
    }
    return bright;
  }, screenshot.toString('base64'));
  assert.ok(visible > 250, `Expected visible procedural island pixels, found only ${visible}`);

  await page.locator('#night').click();
  assert.equal(await page.locator('#night').getAttribute('aria-pressed'), 'true');
  await page.locator('#viewport').screenshot({path: join(shotDir, 'world-night.png')});
  await page.locator('#hint').click();
  await page.waitForFunction(() => document.querySelector('#count')?.textContent !== '0 / 5', null, {timeout: 30000});
  const progress = await page.locator('#count').textContent();
  assert.notEqual(progress, '0 / 5', 'Scout failed to collect a beacon on real Three.js');

  // Actual browser download and reload should preserve the adventure passport.
  const savePromise = page.waitForEvent('download');
  await page.locator('#save').click();
  const saved = await savePromise;
  const savePath = await saved.path();
  const json = await readFile(savePath);
  const receipt = JSON.parse(json.toString());
  assert.equal(receipt.version, 2);
  assert.equal(receipt.adventure.collectedCells.length, Number(progress.trim().split(' ')[0]));
  await page.locator('#remix').click();
  await page.locator('#load').setInputFiles({ name:'pocket-world.json', mimeType:'application/json', buffer: json });
  await page.waitForFunction(() => document.querySelector('#source-label')?.textContent === 'Restored world');
  assert.equal(await page.locator('#count').textContent(), progress);
  assert.deepEqual(errors, [], 'browser page errors');
  await writeFile(join(shotDir, 'verification.json'), JSON.stringify({
    webgl, brightSubjectPixels: visible, collected: progress, receiptVersion: receipt.version,
    errorCount: errors.length,
  }, null, 2));
  console.log(`PASS real WebGL r169, ${visible} visible island pixels, beacons ${progress}, JSON v2 restored`);
} finally {
  if (browser) await browser.close();
  await new Promise(resolveClose => server.close(resolveClose));
}
