#!/usr/bin/env node
/** Export the executed world-space triangle meshes for forge geometry gates.
 * Browser transport uses an optional, locally installed Playwright; core extraction
 * is dependency-free and exported for deterministic tests.
 */
import { rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';

export function collectMeshGeometry(options = {}) {
  // Deliberately self-contained: Playwright serializes this function into the page.
  const handle = options.viewerHandle || '__IMG2THREEJS_VIEWER__';
  const viewer = globalThis[handle];
  const scene = viewer?.scene;
  // The showcase also renders studio/ground meshes outside its model root.
  const root = viewer?.explodeRoot?.traverse ? viewer.explodeRoot
    : viewer?.modelRoot?.traverse ? viewer.modelRoot : scene;
  if (!scene || !root || typeof root.traverse !== 'function') {
    throw new Error(`viewer ${handle} has no traversable scene`);
  }
  const include = options.include ? new RegExp(options.include) : null;
  const exclude = options.exclude ? new RegExp(options.exclude) : null;
  const cap = options.maxTriangles ?? 50000;
  for (const [key, value] of Object.entries({ maxTriangles: cap,
    maxVertices: options.maxVertices ?? 300000,
    maxInstances: options.maxInstances ?? 1000,
    maxTotalTriangles: options.maxTotalTriangles ?? 100000 })) {
    if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${key} must be a positive integer`);
  }
  scene.updateMatrixWorld?.(true);
  const meshes = [];
  const skippedMeshes = [];
  let exportedTriangles = 0;
  let exportedVertices = 0;
  let named = 0;
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const attrAt = (attr, i) => [attr.getX(i), attr.getY(i), attr.getZ(i)];
  const multiply = (left, right) => {
    const out = new Array(16);
    for (let col = 0; col < 4; col++) for (let row = 0; row < 4; row++) {
      let sum = 0;
      for (let k = 0; k < 4; k++) sum += left[k * 4 + row] * right[col * 4 + k];
      out[col * 4 + row] = sum;
    }
    return out;
  };
  const collect = (mesh) => {
    if (!mesh?.isMesh) return;
    const name = mesh.name || `unnamed-mesh-${++named}`;
    const skip = (reason) => skippedMeshes.push({ name, reason });
    for (let parent = mesh; parent; parent = parent.parent) {
      if (parent.visible === false) return skip('hidden');
    }
    if ((include && !include.test(name)) || (exclude && exclude.test(name))) return skip('filtered');
    if (mesh.isSkinnedMesh) return skip('skinned-mesh');
    if (mesh.isInstancedMesh) {
      const count = mesh.count;
      const limit = options.maxInstances ?? 1000;
      const instances = mesh.instanceMatrix?.array;
      if (!Number.isSafeInteger(count) || count < 1 || count > limit) return skip('instance-count-budget');
      if (!instances || instances.length < count * 16) return skip('missing-instance-matrices');
      const world = mesh.matrixWorld?.elements;
      if (!world || world.length !== 16 || !Array.from(world).every(Number.isFinite)) return skip('invalid-world-matrix');
      const tintAttr = mesh.instanceColor;
      if (tintAttr && tintAttr.count < count) return skip('invalid-instance-colors');
      for (let i = 0; i < count; i++) {
        const matrix = multiply(world, instances.slice(16 * i, 16 * (i + 1)));
        if (!matrix.every(Number.isFinite)) return skip('invalid-instance-world-matrix');
        const tint = tintAttr ? attrAt(tintAttr, i) : null;
        if (tint && !tint.every(Number.isFinite)) return skip('invalid-instance-colors');
        const original = mesh.geometry;
        const geometry = tint ? {
          index: original.index, drawRange: original.drawRange,
          getAttribute(kind) {
            const base = original.getAttribute(kind);
            if (kind !== 'color') return base;
            const count = original.getAttribute('position')?.count || 0;
            return { count,
              getX: k => (base ? base.getX(k) : 1) * tint[0],
              getY: k => (base ? base.getY(k) : 1) * tint[1],
              getZ: k => (base ? base.getZ(k) : 1) * tint[2],
            };
          }
        } : original;
        collect({ isMesh: true, name: `${name}[${i}]`, visible: true, parent: mesh.parent,
          matrixWorld: { elements: matrix }, geometry });
      }
      return;
    }
    if (mesh.morphTargetInfluences?.some((value) => value !== 0)) return skip('active-morph-targets');
    const geometry = mesh.geometry;
    const position = geometry?.getAttribute?.('position');
    if (!position || !Number.isSafeInteger(position.count) || position.count < 3) return skip('missing-position');
    const indexed = geometry.index;
    const available = indexed ? indexed.count : position.count;
    const start = geometry.drawRange?.start ?? 0;
    const count = geometry.drawRange?.count ?? Infinity;
    const end = Math.min(available, start + count);
    if (![start, end].every(Number.isSafeInteger) || start < 0 || end <= start || start % 3 || (end - start) % 3) {
      return skip('invalid-triangle-range');
    }
    // A partial drawRange cannot certify the full mesh in an off-axis gate.
    if (start !== 0 || end !== available) return skip('partial-draw-range');
    if ((end - start) / 3 > cap) return skip('triangle-cap');
    if (exportedTriangles + (end - start) / 3 > (options.maxTotalTriangles ?? 100000)) return skip('total-triangle-budget');
    if (exportedVertices + position.count > (options.maxVertices ?? 300000)) return skip('vertex-budget');
    const e = mesh.matrixWorld?.elements;
    if (!e || e.length !== 16 || !Array.from(e).every(Number.isFinite)) return skip('invalid-world-matrix');
    const a = [e[0], e[1], e[2]], b = [e[4], e[5], e[6]], c = [e[8], e[9], e[10]];
    const n0 = cross(b, c), n1 = cross(c, a), n2 = cross(a, b);
    const det = dot(a, n0);
    if (Math.abs(det) < 1e-12) return skip('singular-world-matrix');
    const normalsAttr = geometry.getAttribute('normal');
    const colorsAttr = geometry.getAttribute('color');
    if (normalsAttr && normalsAttr.count !== position.count) return skip('normal-count-mismatch');
    if (colorsAttr && colorsAttr.count !== position.count) return skip('color-count-mismatch');
    const vertices = [], positions = [], normals = [], colors = [], indices = [];
    for (let i = 0; i < position.count; i++) {
      const p = attrAt(position, i);
      if (!p.every(Number.isFinite)) return skip('nonfinite-position');
      const v = [
        e[0] * p[0] + e[4] * p[1] + e[8] * p[2] + e[12],
        e[1] * p[0] + e[5] * p[1] + e[9] * p[2] + e[13],
        e[2] * p[0] + e[6] * p[1] + e[10] * p[2] + e[14],
      ];
      if (!v.every(Number.isFinite)) return skip('nonfinite-world-position');
      vertices.push(v);
      positions.push(...v);
      if (normalsAttr) {
        const n = attrAt(normalsAttr, i);
        if (!n.every(Number.isFinite)) return skip('nonfinite-normal');
        const transformed = [0, 1, 2].map(j => (n0[j] * n[0] + n1[j] * n[1] + n2[j] * n[2]) / det);
        const length = Math.hypot(...transformed);
        if (!Number.isFinite(length) || length < 1e-12) return skip('invalid-normal');
        normals.push(transformed.map(x => x === 0 ? 0 : x / length));
      }
      if (colorsAttr) {
        const color = attrAt(colorsAttr, i);
        if (!color.every(Number.isFinite)) return skip('nonfinite-color');
        colors.push(...color);
      }
    }
    for (let i = start; i < end; i += 3) {
      const tri = [i, i + 1, i + 2].map(offset => indexed ? indexed.getX(offset) : offset);
      if (!tri.every(index => Number.isSafeInteger(index) && index >= 0 && index < position.count)) {
        return skip('invalid-index');
      }
      if (det < 0) [tri[1], tri[2]] = [tri[2], tri[1]];
      indices.push(...tri);
    }
    const result = { name, vertices, positions, indices, triangleCount: indices.length / 3 };
    if (normalsAttr) result.normals = normals;
    if (colorsAttr) result.colors = colors;
    meshes.push(result);
    exportedTriangles += result.triangleCount;
    exportedVertices += position.count;
  };
  root.traverse(collect);
  const incomplete = meshes.length === 0 || skippedMeshes.some(m => !['filtered', 'hidden'].includes(m.reason));
  return { schemaVersion: 1, coordinateSpace: 'world', meshes, skippedMeshes, incomplete };
}

/** Wait for a real, capture-ready subject, not the first partially mounted mesh.
 * Keep self-contained: Playwright serializes this function into the page. */
export function captureReady({ handle = '__IMG2THREEJS_VIEWER__', flag } = {}) {
  const viewer = globalThis[handle];
  const scene = viewer?.scene;
  const root = viewer?.explodeRoot?.traverse ? viewer.explodeRoot
    : viewer?.modelRoot?.traverse ? viewer.modelRoot : scene;
  if (!scene || !root || typeof root.traverse !== 'function' || viewer?.disposed === true) return false;
  // Viewer.start() can lag behind build(): a geometry handle alone is not readiness.
  if (viewer.started === false) return false;
  let found = false;
  root.traverse(node => { if (node?.isMesh) found = true; });
  if (!found) return false;
  if (flag) return globalThis[flag] === true;
  // The official showcase publishes this flag after loading + a few render frames.
  // Once declared, false means "not ready", never "flag is optional".
  if ('__IMG2THREEJS_READY__' in globalThis) return globalThis.__IMG2THREEJS_READY__ === true;
  // Third-party previews without a readiness contract remain compatible. They can
  // opt into a hard readiness gate with --ready-flag NAME.
  return true;
}

function parseArgs(argv) {
  const opts = {};
  if (argv.includes('--help') || argv.includes('-h')) return { help: true };
  const names = new Map([['--url', 'url'], ['--out', 'out'], ['--include', 'include'], ['--exclude', 'exclude'],
    ['--max-triangles', 'maxTriangles'], ['--ready-flag', 'readyFlag'], ['--viewer-handle', 'viewerHandle'],
    ['--timeout-ms', 'timeoutMs'], ['--max-instances', 'maxInstances'],
    ['--max-vertices', 'maxVertices'], ['--max-total-triangles', 'maxTotalTriangles']]);
  for (let i = 0; i < argv.length; i++) {
    const key = names.get(argv[i]);
    if (!key || !argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error(`invalid argument: ${argv[i]}`);
    opts[key] = argv[++i];
  }
  if (!opts.url || !opts.out) throw new Error('both --url and --out are required');
  const url = new URL(opts.url);
  if (!['http:', 'https:', 'file:'].includes(url.protocol)) throw new Error('unsupported preview URL protocol');
  for (const prop of ['include', 'exclude']) if (opts[prop]) new RegExp(opts[prop]);
  for (const prop of ['maxTriangles', 'maxInstances', 'maxVertices', 'maxTotalTriangles', 'timeoutMs']) if (opts[prop] !== undefined) {
    const n = Number(opts[prop]);
    if (!Number.isSafeInteger(n) || n < 1) throw new Error(`${prop} must be a positive integer`);
    opts[prop] = n;
  }
  return opts;
}

function loadPlaywright() {
  const roots = [process.cwd(), process.env.IMG2THREEJS_SHOWCASE_ROOT].filter(Boolean);
  for (const root of roots) {
    try {
      const p = createRequire(join(resolve(root), 'package.json'))('playwright');
      if (p.chromium) return p;
    } catch (error) {
      if (error.code !== 'MODULE_NOT_FOUND') throw error;
    }
  }
  throw new Error('Playwright not installed in working directory or IMG2THREEJS_SHOWCASE_ROOT; install it in your browser test project (not in the core skill)');
}

export async function runCli(argv = process.argv.slice(2)) {
  const opts = parseArgs(argv);
  if (opts.help) {
    process.stdout.write('Usage: node runtime/scripts/export_mesh_geometry.mjs --url URL --out meshes.json [--include RE] [--exclude RE] [--max-triangles N] [--ready-flag F] [--viewer-handle H] [--timeout-ms N]\n');
    return 0;
  }
  // Invalidate stale successful/diagnostic receipts before browser capture.
  await Promise.all([rm(opts.out, { force: true }), rm(`${opts.out}.incomplete.json`, { force: true })]);
  const playwright = loadPlaywright();
  const browser = await playwright.chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.goto(opts.url, { waitUntil: 'domcontentloaded', timeout: opts.timeoutMs ?? 30000 });
    await page.waitForFunction(captureReady,
      { handle: opts.viewerHandle || '__IMG2THREEJS_VIEWER__', flag: opts.readyFlag },
      { timeout: opts.timeoutMs ?? 30000 });
    const report = await page.evaluate(collectMeshGeometry, opts);
    if (report.incomplete) {
      const diagnostics = `${opts.out}.incomplete.json`;
      await writeFile(diagnostics, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
      process.stderr.write(`Incomplete mesh export: ${report.skippedMeshes.length} skipped; see ${diagnostics}\n`);
      return 2;
    }
    await writeFile(opts.out, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    return 0;
  } finally {
    await browser.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  runCli().then(code => { process.exitCode = code; }).catch(error => {
    process.stderr.write(`mesh exporter: ${error.message}\n`);
    process.exitCode = 2;
  });
}