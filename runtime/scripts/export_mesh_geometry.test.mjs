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
  const subjectRoot = { traverse(fn) { for (const mesh of meshes) fn(mesh); } };
  globalThis.__TEST_MESH_VIEWER__ = {
    scene: { updateMatrixWorld() {}, traverse(fn) { for (const mesh of meshes) fn(mesh); } },
    modelRoot: subjectRoot,
  };
  return { viewerHandle: '__TEST_MESH_VIEWER__' };
};
afterEach(() => {
  delete globalThis.__TEST_MESH_VIEWER__;
  delete globalThis.__IMG2THREEJS_READY__;
  delete globalThis.__CUSTOM_MESH_READY__;
  delete globalThis.__IMG2THREEJS_MESH_ROOT__;
  delete globalThis.__IMG2THREEJS_CAPTURE__;
});

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
  viewer.modelRoot.traverse = () => {};
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
  assert.equal(result.rootSource, 'modelRoot');
  assert.equal(result.sceneRootOptIn, false);
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

test('explicit global subject root takes precedence over viewer scene', () => {
  const studio = makeMesh('studio-floor');
  const subject = makeMesh('actual-subject');
  const opts = install(studio);
  delete globalThis.__TEST_MESH_VIEWER__.modelRoot;
  let refreshed = false;
  globalThis.__IMG2THREEJS_MESH_ROOT__ = {
    updateWorldMatrix() { refreshed = true; },
    traverse(fn) { fn(subject); },
  };
  const report = collectMeshGeometry(opts);
  assert.equal(refreshed, true, 'explicit detached root must update matrices');
  assert.equal(report.rootSource, 'explicit-global');
  assert.deepEqual(report.meshes.map(m => m.name), ['actual-subject']);
  assert.equal(captureReady({ handle: opts.viewerHandle }), true);
});

test('capture-provided subject root is used without falling back to studio', () => {
  const studio = makeMesh('studio-floor');
  const subject = makeMesh('capture-subject');
  const opts = install(studio);
  delete globalThis.__TEST_MESH_VIEWER__.modelRoot;
  globalThis.__IMG2THREEJS_CAPTURE__ = {getModelRoot() {
    return { traverse(fn) { fn(subject); } };
  }};
  const result = collectMeshGeometry(opts);
  assert.equal(result.rootSource, 'capture-model-root');
  assert.deepEqual(result.meshes.map(m => m.name), ['capture-subject']);
  assert.equal(captureReady({ handle: opts.viewerHandle }), true);
});

test('standalone global subject root requires a true readiness signal', () => {
  const subject = makeMesh('unwrapped-subject');
  globalThis.__IMG2THREEJS_MESH_ROOT__ = {
    traverse(fn) { fn(subject); },
    updateWorldMatrix() {},
  };
  assert.equal(captureReady(), false);
  globalThis.__IMG2THREEJS_READY__ = 'true';
  assert.equal(captureReady(), false);
  globalThis.__IMG2THREEJS_READY__ = true;
  assert.equal(captureReady(), true);
  const result = collectMeshGeometry();
  assert.equal(result.rootSource, 'explicit-global');
  assert.deepEqual(result.meshes.map(m => m.name), ['unwrapped-subject']);
});

test('studio-only scenes do not pass the subject-root gate by default', () => {
  const studio = makeMesh('studio-ground');
  const opts = install(studio);
  const viewer = globalThis.__TEST_MESH_VIEWER__;
  delete viewer.modelRoot;
  globalThis.__IMG2THREEJS_READY__ = true;
  assert.equal(captureReady({ handle: opts.viewerHandle }), false);
  assert.throws(() => collectMeshGeometry(opts), /explicit subject root/);
  // Deliberate generic whole-scene inspection stays possible, but the receipt
  // must say that subject-specific completeness is not established.
  assert.equal(captureReady({ handle: opts.viewerHandle, allowSceneRoot: true }), true);
  const report = collectMeshGeometry({ ...opts, allowSceneRoot: true });
  assert.equal(report.rootSource, 'scene-explicit');
  assert.equal(report.sceneRootOptIn, true);
  assert.deepEqual(report.meshes.map(x => x.name), ['studio-ground']);
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

test('static instance matrices and tints expand into independently checkable meshes', () => {
  const copies = makeMesh('copies');
  copies.isInstancedMesh = true;
  copies.count = 2;
  const second = [...IDENTITY];
  second[12] = 4;
  copies.instanceMatrix = { array: [...IDENTITY, ...second] };
  copies.instanceColor = attr([[1, 0, 0], [0, 1, 0]]);
  const opts = install(copies);
  const result = collectMeshGeometry(opts);
  assert.equal(result.incomplete, false);
  assert.deepEqual(result.meshes.map(m => m.name), ['copies[0]', 'copies[1]']);
  assert.deepEqual(result.meshes[0].vertices[1], [1, 0, 0]);
  assert.deepEqual(result.meshes[1].vertices[1], [5, 0, 0]);
  assert.deepEqual(result.meshes[0].colors.slice(0, 3), [1, 0, 0]);
  assert.deepEqual(result.meshes[1].colors.slice(0, 3), [0, 0, 0]);
  assert.deepEqual(result.meshes[1].colors.slice(3, 6), [0, 1, 0]);
});

test('instance budgets and missing matrices fail closed', () => {
  const copies = makeMesh('copies');
  copies.isInstancedMesh = true;
  copies.count = 2;
  copies.instanceMatrix = {array: [...IDENTITY, ...IDENTITY]};
  const opts = install(copies);
  const capped = collectMeshGeometry({...opts, maxInstances: 1});
  assert.equal(capped.incomplete, true);
  assert.deepEqual(capped.skippedMeshes.map(m => m.reason), ['instance-count-budget']);
  const vertexCapped = collectMeshGeometry({...opts, maxVertices: 3});
  assert.equal(vertexCapped.incomplete, true);
  assert.equal(vertexCapped.meshes.length, 1);
  assert.deepEqual(vertexCapped.skippedMeshes.map(m => m.reason), ['vertex-budget']);
  const triangleCapped = collectMeshGeometry({...opts, maxTotalTriangles: 1});
  assert.equal(triangleCapped.incomplete, true);
  assert.equal(triangleCapped.meshes.length, 1);
  copies.instanceMatrix = null;
  assert.deepEqual(collectMeshGeometry(opts).skippedMeshes.map(m => m.reason), ['missing-instance-matrices']);
});

test('active instanced morph poses are not exported as unchanged geometry', () => {
  const copies = makeMesh('morph-copies');
  copies.isInstancedMesh = true;
  copies.count = 1;
  copies.instanceMatrix = { array: [...IDENTITY] };
  const opts = install(copies);
  copies.morphTexture = { image: { data: Float32Array.of(1) } };
  let result = collectMeshGeometry(opts);
  assert.equal(result.incomplete, true);
  assert.equal(result.meshes.length, 0);
  assert.deepEqual(result.skippedMeshes.map(m => m.reason), ['active-morph-targets']);

  copies.morphTexture = null;
  copies.morphTargetInfluences = [0.25];
  result = collectMeshGeometry(opts);
  assert.equal(result.incomplete, true);
  assert.deepEqual(result.skippedMeshes.map(m => m.reason), ['active-morph-targets']);

  copies.morphTargetInfluences = [0];
  result = collectMeshGeometry(opts);
  assert.equal(result.incomplete, false, 'neutral static instances remain supported');
  assert.deepEqual(result.meshes.map(m => m.name), ['morph-copies[0]']);
});

test('skinned meshes remain explicitly incomplete evidence', () => {
  const skin = makeMesh('skin');
  skin.isSkinnedMesh = true;
  const opts = install(makeMesh('safe'), skin);
  const result = collectMeshGeometry(opts);
  assert.equal(result.incomplete, true);
  assert.deepEqual(result.meshes.map(x => x.name), ['safe']);
  assert.deepEqual(result.skippedMeshes.map(x => x.reason), ['skinned-mesh']);
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

test('complete visible multi-material groups are valid geometry evidence', () => {
  const grouped = makeMesh('painted');
  grouped.material = [{ visible: true }, { visible: true }];
  grouped.geometry.index = { count: 6, getX: i => i % 3 };
  grouped.geometry.groups = [
    { start: 0, count: 3, materialIndex: 0 },
    { start: 3, count: 3, materialIndex: 1 },
  ];
  const result = collectMeshGeometry(install(grouped));
  assert.equal(result.incomplete, false);
  assert.equal(result.meshes[0].triangleCount, 2);
  assert.deepEqual(result.skippedMeshes, []);
});

test('partial or overlapping multi-material groups cannot certify unseen triangles', () => {
  const mesh = makeMesh('partial-paint');
  mesh.material = [{ visible: true }];
  mesh.geometry.index = { count: 6, getX: i => i % 3 };
  mesh.geometry.groups = [{ start: 0, count: 3, materialIndex: 0 }];
  const options = install(mesh);
  let result = collectMeshGeometry(options);
  assert.equal(result.incomplete, true);
  assert.deepEqual(result.skippedMeshes.map(m => m.reason), ['partial-material-groups']);
  assert.equal(result.meshes.length, 0);

  mesh.geometry.groups = [{ start: 0, count: 6, materialIndex: 0 },
    { start: 0, count: 3, materialIndex: 0 }];
  result = collectMeshGeometry(options);
  assert.equal(result.incomplete, true);
  assert.deepEqual(result.skippedMeshes.map(m => m.reason), ['overlapping-material-groups']);
});

test('missing, invalid and hidden multi-material groups fail closed', () => {
  const mesh = makeMesh('unrendered-material');
  mesh.material = [{ visible: true }];
  const options = install(mesh);
  let result = collectMeshGeometry(options);
  assert.deepEqual(result.skippedMeshes.map(m => m.reason), ['missing-material-groups']);

  mesh.geometry.groups = [{ start: 0, count: 3, materialIndex: 9 }];
  result = collectMeshGeometry(options);
  assert.deepEqual(result.skippedMeshes.map(m => m.reason), ['invalid-material-groups']);

  mesh.geometry.groups = [{ start: 0, count: 3, materialIndex: 0 }];
  mesh.material[0].visible = false;
  result = collectMeshGeometry(options);
  assert.deepEqual(result.skippedMeshes.map(m => m.reason), ['hidden-material-group']);
  assert.equal(result.incomplete, true);
});

test('instanced multi-material expansion preserves group visibility contract', () => {
  const copies = makeMesh('painted-instances');
  copies.material = [{ visible: true }];
  copies.geometry.groups = [{ start: 0, count: 3, materialIndex: 0 }];
  copies.isInstancedMesh = true;
  copies.count = 2;
  copies.instanceMatrix = { array: [...IDENTITY, ...IDENTITY] };
  copies.instanceColor = attr([[1, 1, 1], [1, 1, 1]]);
  const options = install(copies);
  assert.equal(collectMeshGeometry(options).incomplete, false);
  copies.material[0].visible = false;
  const invalid = collectMeshGeometry(options);
  assert.equal(invalid.incomplete, true);
  assert.deepEqual(invalid.skippedMeshes.map(m => m.reason),
    ['hidden-material-group', 'hidden-material-group']);
  assert.equal(invalid.meshes.length, 0);
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
  assert.match(ok.stdout, /--allow-scene-root/);
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
      const handlers = {};
      module.exports = { chromium: { launch: async () => ({
        newPage: async () => ({
          on: (name, handler) => { handlers[name] = handler; },
          goto: async () => {
            const items = [tri('subject')];
            if (process.env.SIMULATE_INCOMPLETE) items.push(tri('skin',true));
            if (process.env.SIMULATE_PAGE_ERROR) handlers.pageerror?.(new Error('broken preview despite ready geometry'));
            globalThis.__IMG2THREEJS_VIEWER__ = {scene: {updateMatrixWorld(){}, traverse(fn){items.forEach(fn);}},
              modelRoot: {traverse(fn){items.forEach(fn);}}};
          },
          waitForFunction: async (fn,arg) => { if (!fn(arg)) throw new Error('not ready'); },
          evaluate: async (fn,arg) => fn(arg),
        }),
        close: async () => {},
      }) } };
    `);
    const script = fileURLToPath(new URL('./export_mesh_geometry.mjs', import.meta.url));
    for (const [partial, pageError] of [[false, false], [true, false], [false, true]]) {
      const out = join(dir, 'nested', pageError ? 'broken-page.json' : partial ? 'partial.json' : 'complete.json');
      mkdirSync(join(dir, 'nested'), {recursive:true});
      writeFileSync(out, 'stale successful evidence', 'utf8');
      const res = spawnSync(process.execPath, [script, '--url', 'http://localhost:5173/#/demo/example', '--out', out], {
        cwd: dir, encoding: 'utf8', env: { ...process.env,
          SIMULATE_INCOMPLETE: partial ? '1' : '', SIMULATE_PAGE_ERROR: pageError ? '1' : '' },
      });
      assert.equal(res.status, partial || pageError ? 2 : 0, res.stderr);
      const diagnostics = `${out}.incomplete.json`;
      assert.equal(existsSync(out), !(partial || pageError), 'failed capture must not leave successful evidence');
      assert.equal(existsSync(diagnostics), partial || pageError);
      const report = JSON.parse(readFileSync(partial || pageError ? diagnostics : out, 'utf8'));
      assert.equal(report.meshes[0].triangleCount, 1);
      assert.deepEqual(report.meshes[0].indices, [0, 1, 2]);
      assert.equal(report.incomplete, partial || pageError);
      if (pageError) assert.deepEqual(report.browserErrors, ['broken preview despite ready geometry']);
      assert.equal(report.rootSource, 'modelRoot');
      assert.equal(report.sceneRootOptIn, false);
    }
  } finally { rmSync(dir, { recursive: true, force: true }); }
});