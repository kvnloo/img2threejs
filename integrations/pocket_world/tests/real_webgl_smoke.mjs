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
// Read-only observers are appended only to the test bundle, never the preview.
const observer = `
globalThis.__pocketSmoke = {
  snapshot: () => ({scoutCell, scoutDestination, collected, relief}),
  tapTarget: () => {
    const rect = canvas.getBoundingClientRect();
    const picker = new THREE.Raycaster();
    for (const cell of cells) {
      if (cell === scoutCell) continue;
      const [x, , z] = positionOf(cell, 0);
      const point = new THREE.Vector3(x, tileHeight(data.heights[cell], relief), z).project(camera);
      const clientX = rect.left + (point.x + 1) * rect.width / 2;
      const clientY = rect.top + (1 - point.y) * rect.height / 2;
      if (clientX < 20 || clientY < 20 || clientX > rect.right - 20 || clientY > rect.bottom - 20 ||
          document.elementFromPoint(clientX, clientY) !== canvas) continue;
      picker.setFromCamera(new THREE.Vector2(point.x, point.y), camera);
      if (picker.intersectObjects(beacons.filter(beacon => beacon.visible), false).length) continue;
      const hit = picker.intersectObject(world, false)[0];
      if (hit && cells[hit.instanceId] === cell) return {x:clientX, y:clientY, cell};
    }
    return null;
  },
};`;

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
      bundler.onLoad({ filter: /[\\/]app\.mjs$/ }, async args => ({
        contents: (await readFile(args.path, 'utf8')) + '\n' + observer,
        loader: 'js',
        resolveDir: dirname(args.path),
      }));
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
  // Touch emulation uses the actual app, OrbitControls and browser capture.
  // It is not a claim of physical Android/iOS device performance.
  const mobile = await browser.newPage({
    viewport: {width: 390, height: 844}, deviceScaleFactor: 2,
    isMobile: true, hasTouch: true, acceptDownloads: true,
  });
  mobile.on('pageerror', error => errors.push(String(error)));
  await mobile.goto(url, {waitUntil: 'domcontentloaded'});
  await mobile.waitForFunction(() => globalThis.__pocketSmoke?.tapTarget());
  const target = await mobile.evaluate(() => globalThis.__pocketSmoke.tapTarget());
  assert.ok(target, 'mobile controls cover all tappable terrain');
  await mobile.touchscreen.tap(target.x, target.y);
  await mobile.waitForFunction(cell => {
    const state = globalThis.__pocketSmoke.snapshot();
    return state.scoutCell === cell && state.scoutDestination === -1;
  }, target.cell, {timeout: 30000});

  const beforePinch = await mobile.evaluate(() => globalThis.__pocketSmoke.snapshot());
  const center = await mobile.evaluate(() => globalThis.__pocketSmoke.tapTarget());
  assert.ok(center, 'mobile terrain unavailable after navigation');
  const session = await mobile.context().newCDPSession(mobile);
  const first = {x:center.x, y:center.y, id:1};
  const second = {x:center.x + 16, y:center.y, id:2};
  await session.send('Input.dispatchTouchEvent', {type:'touchStart', touchPoints:[first]});
  await session.send('Input.dispatchTouchEvent', {type:'touchStart', touchPoints:[first, second]});
  await session.send('Input.dispatchTouchEvent', {type:'touchMove', touchPoints:[
    {...first, x:first.x - 5}, {...second, x:second.x + 5},
  ]});
  await session.send('Input.dispatchTouchEvent', {type:'touchEnd', touchPoints:[]});
  await session.detach();
  assert.deepEqual(await mobile.evaluate(() => globalThis.__pocketSmoke.snapshot()), beforePinch,
    'pinch zoom must not move the scout or collect a beacon');
  await mobile.locator('#viewport').screenshot({path:join(shotDir, 'world-mobile-portrait.png')});
  await mobile.setViewportSize({width:844, height:390});
  await mobile.waitForFunction(() => document.documentElement.scrollWidth <= window.innerWidth);
  await mobile.locator('#hint').scrollIntoViewIfNeeded();
  const landscapeStart = await mobile.evaluate(() => globalThis.__pocketSmoke.snapshot().collected);
  await mobile.locator('#hint').tap();
  await mobile.waitForFunction(previous => {
    const state = globalThis.__pocketSmoke.snapshot();
    return state.collected > previous && state.scoutDestination === -1;
  }, landscapeStart, {timeout:30000});
  await mobile.locator('#viewport').screenshot({path:join(shotDir, 'world-mobile-landscape.png')});
  const mobileState = await mobile.evaluate(() => globalThis.__pocketSmoke.snapshot());
  await mobile.close();
  assert.deepEqual(errors, [], 'browser page errors');
  await writeFile(join(shotDir, 'verification.json'), JSON.stringify({
    webgl, brightSubjectPixels: visible, collected: progress, receiptVersion: receipt.version,
    errorCount: errors.length,
    mobileEmulation: {touchTarget:target.cell, pinchPreservedAdventure:true, landscapeStart, landscapeCollected:mobileState.collected},
  }, null, 2));
  console.log(`PASS real WebGL r169, ${visible} visible island pixels, beacons ${progress}, JSON v2 restored, mobile touch/pinch/landscape passed`);
} finally {
  if (browser) await browser.close();
  await new Promise(resolveClose => server.close(resolveClose));
}
