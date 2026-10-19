#!/usr/bin/env node
// Native Three.js browser capture for real_render_smoke.py.
// This intentionally fails instead of substituting fabricated screenshot scores.
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { chromium } from 'playwright-core';

const out = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: node real_browser_capture.mjs OUT_DIR');
const manifest = JSON.parse(fs.readFileSync(path.join(out, 'manifest.json'), 'utf8'));
if (manifest.status !== 'prepared-not-rendered') throw new Error('manifest must be prepared, not scored');
// Variants live in RUNNER_TEMP; their generated TypeScript must resolve the
// isolated package install beside this script, not search RUNNER_TEMP.
const nodeModules = path.join(path.dirname(fileURLToPath(import.meta.url)), 'node_modules');
if (!fs.existsSync(path.join(nodeModules, 'three'))) throw new Error('isolated Three.js install missing');
const chrome = process.env.CHROME_BIN || '/usr/bin/google-chrome';
if (!fs.existsSync(chrome)) throw new Error('Chromium/Chrome executable not found: ' + chrome);
const browser = await chromium.launch({
  headless: true,
  executablePath: chrome,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--enable-webgl',
    '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
});
try {
  for (const variant of manifest.variants) {
    if (!/^(target|root|c[01]-(minus|plus))$/.test(variant.name)) {
      throw new Error('unexpected variant path: ' + variant.name);
    }
    const folder = path.join(out, variant.name);
    await build({
      entryPoints: [path.join(folder, 'viewer.ts')],
      nodePaths: [nodeModules],
      outfile: path.join(folder, 'bundle.js'),
      bundle: true,
      platform: 'browser',
      format: 'iife',
      target: 'es2020',
      logLevel: 'warning',
    });
    const page = await browser.newPage({ viewport: { width: 256, height: 256 }, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    try {
      await page.goto(pathToFileURL(path.join(folder, 'index.html')).href, {
        waitUntil: 'load', timeout: 60000,
      });
      const info = await page.evaluate(() => window.__rsiCapture || null);
      if (errors.length || !info?.ready || typeof info.coverage !== 'number' ||
          !(info.coverage > 0.02 && info.coverage < 0.95)) {
        throw new Error(variant.name + ' WebGL/canvas failed: ' +
          JSON.stringify({ info, errors: errors.slice(0, 4) }));
      }
      const canvas = page.locator('canvas');
      if (await canvas.count() !== 1) throw new Error('expected exactly one canvas');
      await canvas.screenshot({
        path: path.join(folder, 'render.png'),
        omitBackground: true,
        animations: 'disabled',
        timeout: 60000,
      });
      fs.writeFileSync(path.join(folder, 'browser.json'),
        JSON.stringify({ ...info, chromium: await browser.version() }, null, 2) + '\n');
      process.stdout.write(JSON.stringify({ variant: variant.name, ...info }) + '\n');
    } finally {
      await page.close();
    }
  }
} finally {
  await browser.close();
}
