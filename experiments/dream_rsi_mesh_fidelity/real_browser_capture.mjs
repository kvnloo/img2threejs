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
if (!process.argv[2]) throw new Error(
  'usage: node real_browser_capture.mjs OUT_DIR [--variant NAME --tag CAPTURE_TAG]');
const rest = process.argv.slice(3);
if (rest.length && (rest.length !== 4 || rest[0] !== '--variant' || rest[2] !== '--tag')) {
  throw new Error('live capture requires --variant NAME --tag CAPTURE_TAG');
}
const selectedVariant = rest.length ? rest[1] : null;
const captureTag = rest.length ? rest[3] : null;
if (selectedVariant && !/^(root|c[01]-(minus|plus))$/.test(selectedVariant)) {
  throw new Error('live-budget capture must target a known candidate, not an arbitrary path');
}
if (captureTag && !/^[a-z0-9-]{1,48}$/.test(captureTag)) {
  throw new Error('capture tag must be a bounded lowercase slug');
}
const manifest = JSON.parse(fs.readFileSync(path.join(out, 'manifest.json'), 'utf8'));
if (manifest.status !== 'prepared-not-rendered') throw new Error('manifest must be prepared, not scored');
const variants = selectedVariant
  ? manifest.variants.filter(item => item.name === selectedVariant)
  : manifest.variants;
if (selectedVariant && variants.length !== 1) throw new Error('candidate absent or ambiguous in manifest');

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
  for (const variant of variants) {
    if (!/^(target|root|c[01]-(minus|plus))$/.test(variant.name)) {
      throw new Error('unexpected variant path: ' + variant.name);
    }
    const folder = path.join(out, variant.name);
    const screenshot = path.join(folder, captureTag ? `${captureTag}.png` : 'render.png');
    const receipt = path.join(folder, captureTag ? `${captureTag}.json` : 'browser.json');
    if (captureTag && (fs.existsSync(screenshot) || fs.existsSync(receipt))) {
      throw new Error('live-budget capture already exists; refuse cached or overwritten evidence');
    }
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
      // Retain the screenshot and diagnostics *before* checking coverage,
      // so a clipping/background failure has inspectable pixel evidence.
      const canvas = page.locator('canvas');
      if (await canvas.count() !== 1) throw new Error('expected exactly one canvas');
      await canvas.screenshot({
        path: screenshot,
        omitBackground: true,
        animations: 'disabled',
        timeout: 60000,
      });
      fs.writeFileSync(receipt,
        JSON.stringify({ ...info, chromium: await browser.version(), errors,
          variant: variant.name, captureTag: captureTag ?? null }, null, 2) + '\n');
      if (errors.length || !info?.ready || typeof info.coverage !== 'number' ||
          !(info.coverage > 0.02 && info.coverage < 0.95)) {
        throw new Error(variant.name + ' WebGL/canvas failed: ' +
          JSON.stringify({ info, errors: errors.slice(0, 4) }));
      }
      process.stdout.write(JSON.stringify({ variant: variant.name, captureTag,
        liveCapture: Boolean(captureTag), ...info }) + '\n');
    } finally {
      await page.close();
    }
  }
} finally {
  await browser.close();
}
