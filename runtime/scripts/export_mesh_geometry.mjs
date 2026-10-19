#!/usr/bin/env node
/** Export the executed world-space triangle meshes for forge geometry gates.
 * Browser transport uses an optional, locally installed Playwright; core extraction
 * is dependency-free and exported for deterministic tests.
 */
import { writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';

export function collectMeshGeometry(options = {}) {
  // Deliberately self-contained: Playwright serializes this function into the page.
  const handle = options.viewerHandle || '__IMG2THREEJS_VIEWER__';
  const viewer = globalThis[handle];
  const scene = viewer?.scene;
  // The showcase also renders studio/ground meshes outside its model root. A preview that
  // follows the render-bridge capture contract can name its model root instead.
  const capture = globalThis.__IMG2THREEJS_CAPTURE__;
  const contractRoot = globalThis.__IMG2THREEJS_MESH_ROOT__
    ?? (typeof capture?.getModelRoot === 'function' ? capture.getModelRoot() : capture?.modelRoot);
  const root = viewer?.explodeRoot?.traverse ? viewer.explodeRoot
    : contractRoot?.traverse ? contractRoot : scene;
  if (!root || typeof root.traverse !== 'function') {
    throw new Error(`viewer ${handle} has no traversable scene`);
  }
  const include = options.include ? new RegExp(options.include) : null;
  const exclude = options.exclude ? new RegExp(options.exclude) : null;
  const cap = options.maxTriangles ?? 50000;
  if (!Number.isSafeInteger(cap) || cap < 1) throw new Error('maxTriangles must be a positive integer');
  (scene || root).updateMatrixWorld?.(true);
  const meshes = [];
  const skippedMeshes = [];
  let named = 0;
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const attrAt = (attr, i) => [attr.getX(i), attr.getY(i), attr.getZ(i)];
  // Column-major 4x4 multiply (three.js Matrix4.elements layout).
  const multiply = (l, r) => {
    const out = new Array(16);
    for (let col = 0; col < 4; col++) for (let row = 0; row < 4; row++) {
      let sum = 0;
      for (let k = 0; k < 4; k++) sum += l[k * 4 + row] * r[col * 4 + k];
      out[col * 4 + row] = sum;
    }
    return out;
  };
  root.traverse((mesh) => {
    if (!mesh?.isMesh) return;
    const name = mesh.name || `unnamed-mesh-${++named}`;
    const skip = (reason) => skippedMeshes.push({ name, reason });
    for (let parent = mesh; parent; parent = parent.parent) {
      if (parent.visible === false) return skip('hidden');
    }
    if ((include && !include.test(name)) || (exclude && exclude.test(name))) return skip('filtered');
    if (mesh.isSkinnedMesh) return skip('skinned-mesh');
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
    const world = mesh.matrixWorld?.elements;
    if (!world || world.length !== 16 || !Array.from(world).every(Number.isFinite)) return skip('invalid-world-matrix');
    const normalsAttr = geometry.getAttribute('normal');
    const colorsAttr = geometry.getAttribute('color');
    if (normalsAttr && normalsAttr.count !== position.count) return skip('normal-count-mismatch');
    if (colorsAttr && colorsAttr.count !== position.count) return skip('color-count-mismatch');

    // One world-space mesh for matrix e. Returns a skip reason, or null after pushing.
    const emit = (label, e) => {
      const a = [e[0], e[1], e[2]], b = [e[4], e[5], e[6]], c = [e[8], e[9], e[10]];
      const n0 = cross(b, c), n1 = cross(c, a), n2 = cross(a, b);
      const det = dot(a, n0);
      if (!Number.isFinite(det) || Math.abs(det) < 1e-12) return 'singular-world-matrix';
      const vertices = [], positions = [], normals = [], colors = [], indices = [];
      for (let i = 0; i < position.count; i++) {
        const p = attrAt(position, i);
        if (!p.every(Number.isFinite)) return 'nonfinite-position';
        const v = [
          e[0] * p[0] + e[4] * p[1] + e[8] * p[2] + e[12],
          e[1] * p[0] + e[5] * p[1] + e[9] * p[2] + e[13],
          e[2] * p[0] + e[6] * p[1] + e[10] * p[2] + e[14],
        ];
        if (!v.every(Number.isFinite)) return 'nonfinite-world-position';
        vertices.push(v);
        positions.push(...v);
        if (normalsAttr) {
          const n = attrAt(normalsAttr, i);
          if (!n.every(Number.isFinite)) return 'nonfinite-normal';
          const transformed = [0, 1, 2].map(j => (n0[j] * n[0] + n1[j] * n[1] + n2[j] * n[2]) / det);
          const length = Math.hypot(...transformed);
          if (!Number.isFinite(length) || length < 1e-12) return 'invalid-normal';
          normals.push(transformed.map(x => x === 0 ? 0 : x / length));
        }
        if (colorsAttr) {
          const color = attrAt(colorsAttr, i);
          if (!color.every(Number.isFinite)) return 'nonfinite-color';
          colors.push(...color);
        }
      }
      for (let i = start; i < end; i += 3) {
        const tri = [i, i + 1, i + 2].map(offset => indexed ? indexed.getX(offset) : offset);
        if (!tri.every(index => Number.isSafeInteger(index) && index >= 0 && index < position.count)) {
          return 'invalid-index';
        }
        if (det < 0) [tri[1], tri[2]] = [tri[2], tri[1]];
        indices.push(...tri);
      }
      const result = { name: label, vertices, positions, indices, triangleCount: indices.length / 3 };
      if (normalsAttr) result.normals = normals;
      if (colorsAttr) result.colors = colors;
      meshes.push(result);
      return null;
    };

    if (!mesh.isInstancedMesh) {
      if ((end - start) / 3 > cap) return skip('triangle-cap');
      const reason = emit(name, Array.from(world));
      return reason ? skip(reason) : undefined;
    }
    // InstancedMesh (the generator's instanced-cluster): one world-space entry per live instance,
    // named name[i], composed as matrixWorld * instanceMatrix[i].
    const instances = mesh.count;
    const array = mesh.instanceMatrix?.array;
    if (!Number.isSafeInteger(instances) || instances < 1 || !array || array.length < instances * 16) {
      return skip('invalid-instance-matrices');
    }
    if ((end - start) / 3 * instances > cap) return skip('triangle-cap');
    const before = meshes.length;
    for (let instance = 0; instance < instances; instance++) {
      const local = Array.from(array.slice(instance * 16, instance * 16 + 16));
      if (!local.every(Number.isFinite)) {
        meshes.length = before;
        return skip('invalid-instance-matrices');
      }
      const reason = emit(`${name}[${instance}]`, multiply(Array.from(world), local));
      if (reason) {
        // All-or-nothing: a partly exported cluster must not look like a smaller clean one.
        meshes.length = before;
        return skip(reason);
      }
    }
  });
  const incomplete = meshes.length === 0 || skippedMeshes.some(m => !['filtered', 'hidden'].includes(m.reason));
  return { schemaVersion: 1, coordinateSpace: 'world', meshes, skippedMeshes, incomplete };
}

function parseArgs(argv) {
  const opts = {};
  if (argv.includes('--help') || argv.includes('-h')) return { help: true };
  const names = new Map([['--url', 'url'], ['--out', 'out'], ['--include', 'include'], ['--exclude', 'exclude'],
    ['--max-triangles', 'maxTriangles'], ['--ready-flag', 'readyFlag'], ['--viewer-handle', 'viewerHandle'],
    ['--timeout-ms', 'timeoutMs']]);
  for (let i = 0; i < argv.length; i++) {
    const key = names.get(argv[i]);
    if (!key || !argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error(`invalid argument: ${argv[i]}`);
    opts[key] = argv[++i];
  }
  if (!opts.url || !opts.out) throw new Error('both --url and --out are required');
  const url = new URL(opts.url);
  if (!['http:', 'https:', 'file:'].includes(url.protocol)) throw new Error('unsupported preview URL protocol');
  for (const prop of ['include', 'exclude']) if (opts[prop]) new RegExp(opts[prop]);
  for (const prop of ['maxTriangles', 'timeoutMs']) if (opts[prop] !== undefined) {
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
  const playwright = loadPlaywright();
  const browser = await playwright.chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.goto(opts.url, { waitUntil: 'domcontentloaded', timeout: opts.timeoutMs ?? 30000 });
    await page.waitForFunction(({ handle, flag }) => {
      const viewer = globalThis[handle];
      const capture = globalThis.__IMG2THREEJS_CAPTURE__;
      const contractRoot = globalThis.__IMG2THREEJS_MESH_ROOT__
        ?? (typeof capture?.getModelRoot === 'function' ? capture.getModelRoot() : capture?.modelRoot);
      const root = viewer?.explodeRoot?.traverse ? viewer.explodeRoot
        : contractRoot?.traverse ? contractRoot : viewer?.scene;
      let found = false;
      root?.traverse?.(node => { if (node.isMesh) found = true; });
      return found && (!flag || globalThis[flag] === true);
    }, { handle: opts.viewerHandle || '__IMG2THREEJS_VIEWER__', flag: opts.readyFlag }, { timeout: opts.timeoutMs ?? 30000 });
    const report = await page.evaluate(collectMeshGeometry, opts);
    await writeFile(opts.out, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    if (report.incomplete) {
      process.stderr.write(`Incomplete mesh export: ${report.skippedMeshes.length} skipped; see ${opts.out}\n`);
      return 2;
    }
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