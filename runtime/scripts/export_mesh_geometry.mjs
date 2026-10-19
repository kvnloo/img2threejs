#!/usr/bin/env node
// Export executed BufferGeometry in world coordinates for the Python geometry gates.
// Playwright is optional and loaded only for live browser captures.
import { createRequire } from 'node:module';
import { writeFile, rm } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';

export function collectMeshGeometry({ viewerHandle = '__IMG2THREEJS_VIEWER__', include = '', exclude = '', maxTriangles = 50000 } = {}) {
  const scene = window[viewerHandle]?.scene;
  if (!scene?.traverse || !scene.updateMatrixWorld) throw new Error('viewer ' + viewerHandle + ' has no Three.js scene');
  const includeRe = include ? new RegExp(include) : null;
  const excludeRe = exclude ? new RegExp(exclude) : null;
  const meshes = [], skipped = [];
  let incomplete = false, ordinal = 0;
  const skip = (name, reason, blocking = false) => {
    skipped.push({ name, reason });
    if (blocking) incomplete = true;
  };
  const cross = (u, v) => [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  scene.updateMatrixWorld(true);
  scene.traverse((mesh) => {
    if (!mesh.isMesh) return;
    const name = mesh.name || 'mesh-' + ordinal;
    ordinal++;
    if (includeRe && !includeRe.test(name)) { skip(name, 'include-filter'); return; }
    if (excludeRe && excludeRe.test(name)) { skip(name, 'exclude-filter'); return; }
    if (function hidden() { for (let node = mesh; node; node = node.parent) if (node.visible === false) return true; return false; }()) {
      skip(name, 'hidden'); return;
    }
    if (mesh.isInstancedMesh || mesh.isSkinnedMesh) { skip(name, 'unsupported-deformed-or-instanced', true); return; }
    if (mesh.morphTargetInfluences?.some(weight => Math.abs(weight) > 1e-9)) {
      skip(name, 'active-morph-target', true); return;
    }
    const geometry = mesh.geometry;
    const positions = geometry?.getAttribute?.('position');
    const normals = geometry?.getAttribute?.('normal');
    const index = geometry?.index;
    const corners = index ? index.count : positions?.count;
    const range = geometry?.drawRange;
    if (!positions || !Number.isInteger(corners) || corners < 3 || corners % 3 !== 0) {
      skip(name, 'missing-or-invalid-triangles', true); return;
    }
    if (range && (range.start !== 0 || (Number.isFinite(range.count) && range.count < corners))) {
      skip(name, 'partial-draw-range', true); return;
    }
    if (corners / 3 > maxTriangles) { skip(name, 'triangle-cap', true); return; }
    const m = mesh.matrixWorld?.elements;
    if (!m || m.length !== 16 || !Array.from(m).every(Number.isFinite)) {
      skip(name, 'invalid-world-matrix', true); return;
    }
    const a = [m[0], m[1], m[2]], b = [m[4], m[5], m[6]], c = [m[8], m[9], m[10]];
    const ca = cross(b, c), cb = cross(c, a), cc = cross(a, b);
    const det = a[0] * ca[0] + a[1] * ca[1] + a[2] * ca[2];
    if (!Number.isFinite(det) || Math.abs(det) < 1e-12) { skip(name, 'singular-world-transform', true); return; }
    const verts = [], transformedNormals = [], indices = [];
    let valid = true;
    for (let i = 0; i < positions.count; i++) {
      const x = positions.getX(i), y = positions.getY(i), z = positions.getZ(i);
      const w = [m[0] * x + m[4] * y + m[8] * z + m[12],
                 m[1] * x + m[5] * y + m[9] * z + m[13],
                 m[2] * x + m[6] * y + m[10] * z + m[14]];
      if (!w.every(Number.isFinite)) { valid = false; break; }
      verts.push(w);
      if (normals && normals.count === positions.count) {
        const nx = normals.getX(i), ny = normals.getY(i), nz = normals.getZ(i);
        const n = [0, 1, 2].map(j => (ca[j] * nx + cb[j] * ny + cc[j] * nz) / det);
        const magnitude = Math.hypot(...n);
        if (!Number.isFinite(magnitude) || magnitude < 1e-12) { valid = false; break; }
        transformedNormals.push(n.map(t => t / magnitude));
      }
    }
    for (let i = 0; valid && i < corners; i++) {
      const vertex = index ? index.getX(i) : i;
      if (!Number.isInteger(vertex) || vertex < 0 || vertex >= positions.count) { valid = false; break; }
      indices.push(vertex);
    }
    if (!valid) { skip(name, 'invalid-vertex-or-normal', true); return; }
    const entry = { name, vertices: verts, indices, triangleCount: corners / 3 };
    if (transformedNormals.length === positions.count) entry.normals = transformedNormals;
    meshes.push(entry);
  });
  return { coordinateSpace: 'world', meshes, skipped, incomplete };
}

function parseArgs(argv) {
  const opt = { maxTriangles: 50000 };
  if (argv.includes('--help')) return null;
  const flags = { '--url': 'url', '--out': 'out', '--include': 'include', '--exclude': 'exclude',
    '--max-triangles': 'maxTriangles', '--ready-flag': 'readyFlag', '--viewer-handle': 'viewerHandle' };
  for (let i = 0; i < argv.length; i += 2) {
    const key = flags[argv[i]];
    if (!key || !argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error('invalid argument: ' + argv[i]);
    opt[key] = argv[i + 1];
  }
  if (!opt.url || !opt.out) throw new Error('--url and --out are required');
  if (!/^https?:\/\//.test(opt.url)) throw new Error('--url must be http(s)');
  opt.maxTriangles = Number(opt.maxTriangles);
  if (!Number.isSafeInteger(opt.maxTriangles) || opt.maxTriangles < 1) throw new Error('--max-triangles must be a positive integer');
  for (const expr of [opt.include, opt.exclude]) if (expr) new RegExp(expr);
  return opt;
}

function playwrightRequire() {
  const candidates = [import.meta.url, join(process.cwd(), 'package.json')];
  if (process.env.IMG2THREEJS_SHOWCASE_ROOT) candidates.push(join(resolve(process.env.IMG2THREEJS_SHOWCASE_ROOT), 'package.json'));
  for (const source of candidates) {
    try { return createRequire(source)('playwright'); } catch (err) {
      if (err.code !== 'MODULE_NOT_FOUND') throw err;
    }
  }
  throw new Error('Playwright not found. Install it in the showcase and set IMG2THREEJS_SHOWCASE_ROOT.');
}

export async function main(argv) {
  let browser;
  try {
    const opt = parseArgs(argv);
    if (!opt) {
      console.log('Usage: node runtime/scripts/export_mesh_geometry.mjs --url URL --out meshes.json [--include RE] [--exclude RE] [--max-triangles N] [--ready-flag F] [--viewer-handle H]');
      return 0;
    }
    // Invalidate stale geometry evidence before attempting a new capture.
    await rm(opt.out, { force: true });
    const { chromium } = playwrightRequire();
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto(opt.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForFunction(handle => Boolean(window[handle]?.scene), opt.viewerHandle || '__IMG2THREEJS_VIEWER__', { timeout: 30000 });
    if (opt.readyFlag) {
      await page.waitForFunction(flag => window[flag] === true, opt.readyFlag, { timeout: 30000 });
    }
    const report = await page.evaluate(collectMeshGeometry, opt);
    if (!report.meshes.length || report.incomplete) {
      await writeFile(opt.out + '.incomplete.json', JSON.stringify(report, null, 2) + '\n');
      console.error('incomplete geometry export: ' + report.meshes.length + ' meshes; ' + JSON.stringify(report.skipped));
      return 2;
    }
    await writeFile(opt.out, JSON.stringify(report, null, 2) + '\n');
    console.log('exported ' + report.meshes.length + ' world-space meshes to ' + opt.out);
    return 0;
  } catch (err) {
    console.error('export_mesh_geometry: ' + err.message);
    return 2;
  } finally {
    if (browser) await browser.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  process.exitCode = await main(process.argv.slice(2));
}
