import assert from 'node:assert/strict';
import { test, afterEach } from 'node:test';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { collectMeshGeometry, captureReady } from './export_mesh_geometry.mjs';

const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
const attr = (vectors) => ({ count: vectors.length, getX: i => vectors[i][0], getY: i => vectors[i][1], getZ: i => vectors[i][2] });
const makeMesh = (name = 'part', matrix = IDENTITY) => ({
  isMesh: true, name, visible: true, parent: null, matrixWorld: { elements: matrix },
  geometry: {
    getAttribute(kind) {
      return {
        position: attr([[0, 0, 0], [1, 0, 0], [0, 1, 0]]),
        normal: attr([[0, 0, 1], [0, 0, 1], [0, 0, 1]]),
        color: attr([[1, 0, 0], [0, 1, 0], [0, 0, 1]]),
      }[kind] || null;
    },
    index: { count: 3, getX: i => i },
    drawRange: { start: 0, count: Infinity },
  },
});
const install = (...meshes) => {
  globalThis.__TEST_MESH_VIEWER__ = {
    scene: { updateMatrixWorld() {}, traverse(fn) { for (const mesh of meshes) fn(mesh); } },
  };
  return { viewerHandle: '__TEST_MESH_VIEWER__' };
};
afterEach(() => { delete globalThis.__TEST_MESH_VIEWER__; delete globalThis.__IMG2THREEJS_READY__; delete globalThis.__CUSTOM_MESH_READY__; });

test('showcase readiness waits for started viewer, frame-ready signal, and actual mesh', () => {
  const opts = install(makeMesh('part'));
  const viewer = globalThis.__TEST_MESH_VIEWER__;
  viewer.started = false;
  assert.equal(captureReady({ handle: opts.viewerHandle }), false);
  viewer.started = true;
  globalThis.__IMG2THREEJS_READY__ = false;
  assert.equal(captureReady({ handle: opts.viewerHandle }), false,
    'geometry alone is not proof that the screenshot capture is ready');
  globalThis.__IMG2THREEJS_READY__ = true;
  assert.equal(captureReady({ handle: opts.viewerHandle }), true);
  viewer.disposed = true;
  assert.equal(captureReady({ handle: opts.viewerHandle }), false);
  viewer.disposed = false;
  viewer.scene.traverse = () => {};
  assert.equal(captureReady({ handle: opts.viewerHandle }), false, 'empty subject must not pass');
});

test('custom preview readiness flag is strict; legacy flagless previews remain compatible', () => {
  const opts = install(makeMesh('part'));
  const handle = opts.viewerHandle;
  assert.equal(captureReady({ handle }), true, 'legacy viewer has no readiness signal');
  globalThis.__CUSTOM_MESH_READY__ = false;
  assert.equal(captureReady({ handle, flag: '__CUSTOM_MESH_READY__' }), false);
  globalThis.__CUSTOM_MESH_READY__ = true;
  assert.equal(captureReady({ handle, flag: '__CUSTOM_MESH_READY__' }), true);
  globalThis.__IMG2THREEJS_READY__ = false;
  assert.equal(captureReady({ handle }), false);
  assert.equal(captureReady({ handle, flag: '__CUSTOM_MESH_READY__' }), true,
    'explicit flag overrides automatic showcase flag');
});

test('exports actual world-space vertices, normal inverse transpose, and vertex colors', () => {
  const matrix = [2, 0, 0, 0, 0, 3, 0, 0, 0, 0, 4, 0, 5, 6, 7, 1];
  const mesh = makeMesh('triangle', matrix);
  const opts = install(mesh);
  const result = collectMeshGeometry(opts);
  assert.equal(result.incomplete, false);
  assert.equal(result.coordinateSpace, 'world');
  assert.deepEqual(result.meshes[0].vertices, [[5, 6, 7], [7, 6, 7], [5, 9, 7]]);
  assert.deepEqual(result.meshes[0].normals, [[0, 0, 1], [0, 0, 1], [0, 0, 1]]);
  assert.deepEqual(result.meshes[0].indices, [0, 1, 2]);
  assert.deepEqual(result.meshes[0].colors, [1, 0, 0, 0, 1, 0, 0, 0, 1]);
  assert.deepEqual(result.meshes[0].positions, [5, 6, 7, 7, 6, 7, 5, 9, 7]);
});

test('prefers the model root over studio and ground meshes', () => {
  const studio = makeMesh('studio-ground');
  const subject = makeMesh('subject');
  const opts = install(studio, subject);
  globalThis.__TEST_MESH_VIEWER__.explodeRoot = { traverse(fn) { fn(subject); } };
  const result = collectMeshGeometry(opts);
  assert.deepEqual(result.meshes.map(m => m.name), ['subject']);
});

test('negative determinant flips triangle winding and transforms normals', () => {
  const matrix = [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  const mesh = makeMesh('mirror', matrix);
  const opts = install(mesh);
  const result = collectMeshGeometry(opts);
  assert.deepEqual(result.meshes[0].indices, [0, 2, 1]);
  assert.deepEqual(result.meshes[0].vertices[1], [-1, 0, 0]);
  assert.deepEqual(result.meshes[0].normals[0], [0, 0, 1]);
});

test('rejects unsupported skinned and instanced meshes without fake clean evidence', () => {
  const skin = makeMesh('skin'); skin.isSkinnedMesh = true;
  const instance = makeMesh('copies'); instance.isInstancedMesh = true;
  const options = install(makeMesh('safe'), skin, instance);
  const result = collectMeshGeometry(options);
  assert.equal(result.meshes.length, 1);
  assert.equal(result.incomplete, true);
  assert.deepEqual(result.skippedMeshes.map(x => x.name), ['skin', 'copies']);
});

test('filters and hidden meshes remain explicitly accounted for', () => {
  const hidden = makeMesh('hidden'); hidden.parent = { visible: false, parent: null };
  const opts = install(makeMesh('left'), makeMesh('right'), hidden);
  const result = collectMeshGeometry({ ...opts, include: '^left$' });
  assert.deepEqual(result.meshes.map(m => m.name), ['left']);
  assert.equal(result.incomplete, false);
  assert.deepEqual(result.skippedMeshes.map(m => m.reason), ['filtered', 'hidden']);
  assert.equal(collectMeshGeometry({ ...opts, include: '^nothing$' }).incomplete, true);
});

test('full non-indexed geometry passes; partial draw ranges are not clean evidence', () => {
  const mesh = makeMesh('nonindexed');
  mesh.geometry.index = null;
  mesh.geometry.getAttribute = kind => kind === 'position'
    ? attr([[0,0,0],[1,0,0],[0,1,0],[0,0,0],[0,1,0],[-1,0,0]]) : null;
  const opts = install(mesh);
  const whole = collectMeshGeometry(opts);
  assert.equal(whole.incomplete, false);
  assert.deepEqual(whole.meshes[0].indices, [0, 1, 2, 3, 4, 5]);
  mesh.geometry.drawRange = { start: 3, count: 3 };
  const partial = collectMeshGeometry(opts);
  assert.equal(partial.incomplete, true);
  assert.deepEqual(partial.skippedMeshes.map(m => m.reason), ['partial-draw-range']);
  assert.equal(partial.meshes.length, 0);
});

test('modelRoot is used before falling back to full studio scene', () => {
  const ground = makeMesh('ground'), subject = makeMesh('subject');
  const opts = install(ground, subject);
  globalThis.__TEST_MESH_VIEWER__.modelRoot = { traverse(fn) { fn(subject); } };
  assert.deepEqual(collectMeshGeometry(opts).meshes.map(m => m.name), ['subject']);
});

test('rejects truncated triangles, oversized meshes, invalid indices and singular matrices', () => {
  const badRange = makeMesh('bad-range'); badRange.geometry.drawRange = { start: 0, count: 2 };
  const badIndex = makeMesh('bad-index'); badIndex.geometry.index.getX = i => i === 2 ? 9 : i;
  const singular = makeMesh('singular', [0,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]);
  const valid = makeMesh('limit');
  const opts = install(badRange, badIndex, singular, valid);
  const result = collectMeshGeometry(opts);
  assert.equal(result.incomplete, true);
  assert.deepEqual(result.skippedMeshes.map(x => x.reason), ['invalid-triangle-range', 'invalid-index', 'singular-world-matrix']);
  assert.throws(() => collectMeshGeometry({ ...opts, maxTriangles: 0 }), /maxTriangles/);
  const oversized = makeMesh('oversized'); oversized.geometry.index = {count:6, getX:i => i%3};
  const cap = collectMeshGeometry({ ...install(oversized), maxTriangles: 1 });
  assert.equal(cap.incomplete, true);
  assert.deepEqual(cap.skippedMeshes.map(m => m.reason), ['triangle-cap']);
});

test('CLI help works with no Playwright, and errors are nonzero with no invalid output', () => {
  const script = fileURLToPath(new URL('./export_mesh_geometry.mjs', import.meta.url));
  const ok = spawnSync(process.execPath, [script, '--help'], { encoding: 'utf8' });
  assert.equal(ok.status, 0, ok.stderr);
  assert.match(ok.stdout, /--max-triangles/);
  const bad = spawnSync(process.execPath, [script, '--url', 'javascript:alert(1)', '--out', '/tmp/no-export.json'], { encoding: 'utf8' });
  assert.equal(bad.status, 2);
  assert.match(bad.stderr, /unsupported preview URL protocol/);
});

test('CLI emits consumer-ready JSON and fails closed on partial export (mocked browser transport)', () => {
  const dir = mkdtempSync(join(tmpdir(), 'img2-mesh-export-'));
  try {
    const moduleDir = join(dir, 'node_modules', 'playwright');
    mkdirSync(moduleDir, { recursive: true });
    writeFileSync(join(moduleDir, 'index.js'), `
      const tri = (name, isSkinnedMesh=false) => ({
        isMesh: true, name, visible: true, isSkinnedMesh, parent: null,
        matrixWorld: { elements: [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1] },
        geometry: { index: null, drawRange: {start:0,count:3},
          getAttribute: (kind) => kind === 'position' ? {count:3, getX:i=>i===1?1:0, getY:i=>i===2?1:0, getZ:i=>0}:null }
      });
      module.exports = { chromium: { launch: async () => ({
        newPage: async () => ({
          goto: async () => {
            const items = [tri('subject')];
            if (process.env.SIMULATE_INCOMPLETE) items.push(tri('skin',true));
            globalThis.__IMG2THREEJS_VIEWER__ = {scene: {updateMatrixWorld(){}, traverse(fn){items.forEach(fn);}}};
          },
          waitForFunction: async (fn,arg) => { if (!fn(arg)) throw new Error('not ready'); },
          evaluate: async (fn,arg) => fn(arg),
        }),
        close: async () => {},
      }) } };
    `);
    const script = fileURLToPath(new URL('./export_mesh_geometry.mjs', import.meta.url));
    for (const partial of [false, true]) {
      const out = join(dir, partial ? 'partial.json' : 'complete.json');
      writeFileSync(out, 'stale successful evidence', 'utf8');
      const res = spawnSync(process.execPath, [script, '--url', 'http://localhost:5173/#/demo/example', '--out', out], {
        cwd: dir, encoding: 'utf8', env: { ...process.env, SIMULATE_INCOMPLETE: partial ? '1' : '' },
      });
      assert.equal(res.status, partial ? 2 : 0, res.stderr);
      const diagnostics = `${out}.incomplete.json`;
      assert.equal(existsSync(out), !partial, 'partial capture must not leave successful evidence');
      assert.equal(existsSync(diagnostics), partial);
      const report = JSON.parse(readFileSync(partial ? diagnostics : out, 'utf8'));
      assert.equal(report.meshes[0].triangleCount, 1);
      assert.deepEqual(report.meshes[0].indices, [0, 1, 2]);
      assert.equal(report.incomplete, partial);
    }
  } finally { rmSync(dir, { recursive: true, force: true }); }
});