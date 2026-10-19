#!/usr/bin/env node
/** End-to-end hinge smoke test: codegen -> TypeScript -> Three.js/WebGL. */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { chromium } from 'playwright';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const temp = mkdtempSync(join(repo, '.hinge-smoke-'));
const screenshots = process.env.HINGE_SCREENSHOTS || join(temp, 'screenshots');
const source = join(temp, 'factory.ts');
const entry = join(temp, 'client.mjs');
let server;
let browser;

try {
  execFileSync('python3', [join(repo, 'forge/tests/emit_hinge_runtime_fixture.py'), source], { stdio: 'inherit' });
  // Compile the emitted TypeScript itself, not a handwritten approximation.
  execFileSync(join(repo, 'node_modules/.bin/tsc'), [
    '--noEmit', '--strict', '--skipLibCheck', '--target', 'es2022', '--module', 'esnext',
    '--moduleResolution', 'bundler', '--lib', 'es2022,dom', source,
  ], { cwd: repo, stdio: 'inherit' });

  writeFileSync(entry, readFileSync(join(repo, 'forge/tests/hinge_runtime_client.mjs'), 'utf8'));
  await build({ entryPoints: [entry], outfile: join(temp, 'bundle.js'),
    bundle: true, format: 'esm', platform: 'browser', logLevel: 'warning' });
  writeFileSync(join(temp, 'index.html'), '<!doctype html><html><head><meta charset="utf-8">' +
    '<style>body{margin:0;background:#eef2f8;display:grid;place-items:center;height:100vh}</style>' +
    '</head><body><script type="module" src="/bundle.js"></script></body></html>');

  server = createServer((req, res) => {
    const path = req.url === '/bundle.js' ? 'bundle.js' :
      req.url === '/index.html' || req.url === '/' ? 'index.html' : null;
    if (!path) return res.writeHead(404).end();
    res.writeHead(200, { 'Content-Type': path.endsWith('.js') ? 'text/javascript' : 'text/html' });
    res.end(readFileSync(join(temp, path)));
  });
  await new Promise((ok, fail) => server.once('error', fail).listen(0, '127.0.0.1', ok));
  browser = await chromium.launch({ headless: true, args: [
    '--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl',
    '--ignore-gpu-blocklist', '--disable-dev-shm-usage',
  ] });
  const page = await browser.newPage({ viewport: { width: 760, height: 560 }, deviceScaleFactor: 1 });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto('http://127.0.0.1:' + server.address().port + '/index.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__hingeReady === true, null, { timeout: 45000 });
  const geometry = await page.evaluate(() => window.__hingeSmoke.testTransforms());
  assert.equal(geometry.hinges, 3);
  mkdirSync(screenshots, { recursive: true });
  for (const angle of [0, 45, 90]) {
    const stats = await page.evaluate(angle => window.__hingeSmoke.render(angle), angle);
    assert.ok(stats.drawCalls >= 1 && stats.triangles > 0, 'blank Three.js render at ' + angle);
    await page.screenshot({ path: join(screenshots, 'hinge-' + angle + '.png') });
  }
  assert.deepEqual(pageErrors, [], 'uncaught browser errors');
  console.log('HINGE_RUNTIME_PASS: TypeScript check, ' + geometry.hinges +
    ' hinges, axis/pivot/nested assertions, WebGL screenshots at 0/45/90 degrees');
  console.log('Screenshots: ' + screenshots);
} finally {
  if (browser) await browser.close();
  if (server) await new Promise(resolve => server.close(resolve));
  rmSync(temp, { recursive: true, force: true });
}
