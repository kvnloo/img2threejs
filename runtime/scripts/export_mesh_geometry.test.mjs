import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { extractMeshGeometry, main } from './export_mesh_geometry.mjs';

const identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
const translate = (x, y, z) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1];
const attribute = (points) => ({
  count: points.length,
  getX: (i) => points[i][0],
  getY: (i) => points[i][1],
  getZ: (i) => points[i][2],
});
const triangle = [[0, 0, 0], [1, 0, 0], [0, 1, 0]];
const normals = [[0, 0, 1], [0, 0, 1], [0, 0, 1]];
function mesh({ name = 'part', vertices = triangle, vertexNormals = normals,
  indices = [0, 1, 2], matrix = identity, vertexColors = null } = {}) {
  return {
    isMesh: true, name, visible: true, children: [],
    matrixWorld: { elements: matrix },
    geometry: {
      attributes: { position: attribute(vertices), normal: vertexNormals && attribute(vertexNormals),
        ...(vertexColors ? { color: attribute(vertexColors) } : {}) },
      index: indices && { count: indices.length, getX: (i) => indices[i] },
      drawRange: { start: 0, count: Infinity },
    },
  };
}
function install(...children) {
  const root = { visible: true, children, updateWorldMatrix() {} };
  globalThis.window = { __IMG2THREEJS_MESH_ROOT__: root };
  return root;
}
afterEach(() => { delete globalThis.window; });

test('indexed BufferGeometry exports world-space vertices, normals, and indices', () => {
  install(mesh({ matrix: translate(2, 3, 4) }));
  const result = extractMeshGeometry();
  assert.deepEqual(result.meshes[0].vertices, [[2, 3, 4], [3, 3, 4], [2, 4, 4]]);
  assert.deepEqual(result.meshes[0].normals, normals);
  assert.deepEqual(result.meshes[0].indices, [0, 1, 2]);
  assert.equal(result.coordinateSpace, 'world');
});

test('non-indexed geometry receives a triangle index array', () => {
  install(mesh({ indices: null }));
  assert.deepEqual(extractMeshGeometry().meshes[0].indices, [0, 1, 2]);
});

test('non-uniform scale uses inverse-transpose for vertex normals', () => {
  const n = 1 / Math.sqrt(2);
  install(mesh({ matrix: [2, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    vertexNormals: [[n, n, 0], [n, n, 0], [n, n, 0]] }));
  const [nx, ny] = extractMeshGeometry().meshes[0].normals[0];
  assert.ok(Math.abs(nx - 1 / Math.sqrt(5)) < 1e-10);
  assert.ok(Math.abs(ny - 2 / Math.sqrt(5)) < 1e-10);
});

test('a mirrored transform reverses winding but preserves outward normal', () => {
  install(mesh({ matrix: [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] }));
  const result = extractMeshGeometry().meshes[0];
  assert.deepEqual(result.indices, [0, 2, 1]);
  result.normals[0].forEach((value, index) => {
    assert.ok(Math.abs(value - [0, 0, 1][index]) < 1e-12);
  });
});

test('instanced mesh exports every instance in world coordinates', () => {
  const node = mesh({ matrix: translate(5, 0, 0) });
  node.isInstancedMesh = true;
  node.count = 2;
  node.instanceMatrix = { array: Float32Array.from([...translate(0, 0, 0), ...translate(10, 0, 0)]) };
  install(node);
  const result = extractMeshGeometry();
  assert.equal(result.meshes.length, 2);
  assert.equal(result.meshes[0].vertices[0][0], 5);
  assert.equal(result.meshes[1].vertices[0][0], 15);
  assert.equal(result.meshes[1].name, 'part[1]');
});

test('only visible descendants are exported', () => {
  const invisible = mesh({ name: 'hidden' });
  invisible.visible = false;
  const node = mesh({ name: 'shown' });
  install(invisible, node);
  assert.deepEqual(extractMeshGeometry().meshes.map((m) => m.name), ['shown']);
});

test('supports existing capture contract model root', () => {
  const root = { children: [mesh()] };
  globalThis.window = { __IMG2THREEJS_CAPTURE__: { getModelRoot: () => root } };
  assert.equal(extractMeshGeometry().meshes.length, 1);
});

test('missing root and empty models fail closed', () => {
  assert.throws(() => extractMeshGeometry(), /MESH_ROOT/);
  install();
  assert.throws(() => extractMeshGeometry(), /No visible triangulated meshes/);
});

test('corrupt geometry and over-budget exports fail closed', () => {
  const node = mesh();
  node.geometry.attributes.normal = null;
  install(node);
  assert.throws(() => extractMeshGeometry(), /vertex normal/);
  const badIndex = mesh({ indices: [0, 1, 9] });
  install(badIndex);
  assert.throws(() => extractMeshGeometry(), /out of range/);
  install(mesh());
  assert.throws(() => extractMeshGeometry({ maxVertices: 2 }), /maxVertices/);
});

test('partial draws, active morphs and skinned meshes fail instead of exporting incorrect evidence', () => {
  const partial = mesh();
  partial.geometry.drawRange = { start: 0, count: 2 };
  install(partial);
  assert.throws(() => extractMeshGeometry(), /partial drawRange/);
  const morphed = mesh();
  morphed.morphTargetInfluences = [0.5];
  install(morphed);
  assert.throws(() => extractMeshGeometry(), /bake skinned\/morphed pose/);
  const skinned = mesh();
  skinned.isSkinnedMesh = true;
  install(skinned);
  assert.throws(() => extractMeshGeometry(), /bake skinned\/morphed pose/);
});

test('documented include/exclude filters preserve selected meshes and refuse empty selections', () => {
  install(mesh({ name: 'panel-left' }), mesh({ name: 'studio-floor' }), mesh({ name: 'panel-right' }));
  const result = extractMeshGeometry({ include: '^panel', exclude: 'right$' });
  assert.deepEqual(result.meshes.map((item) => item.name), ['panel-left']);
  assert.deepEqual(result.skippedMeshes, [
    { name: 'studio-floor', reason: 'filtered' },
    { name: 'panel-right', reason: 'filtered' },
  ]);
  assert.equal(result.incomplete, false);
  assert.throws(() => extractMeshGeometry({ include: '^no-such-mesh$' }), /No visible triangulated meshes/);
  assert.throws(() => extractMeshGeometry({ include: '[' }), /Invalid regular expression/);
});

test('hidden subtrees have honest coverage receipts without contaminating measured geometry', () => {
  const child = mesh({ name: 'hidden-inner' });
  const hidden = { visible: false, children: [mesh({ name: 'hidden-root' }), child] };
  install(mesh({ name: 'shown' }), hidden);
  const result = extractMeshGeometry();
  assert.deepEqual(result.meshes.map((item) => item.name), ['shown']);
  assert.deepEqual(result.skippedMeshes, [
    { name: 'hidden-root', reason: 'hidden' },
    { name: 'hidden-inner', reason: 'hidden' },
  ]);
  assert.equal(result.incomplete, false);
});

test('viewer-handle fallback selects the explicit model root, not the studio scene', () => {
  const root = { children: [mesh({ name: 'subject' })], updateWorldMatrix() {} };
  globalThis.window = { CUSTOM_VIEWER: { explodeRoot: root, scene: { children: [mesh({ name: 'floor' })] } } };
  const result = extractMeshGeometry({ viewerHandle: 'CUSTOM_VIEWER' });
  assert.deepEqual(result.meshes.map((item) => item.name), ['subject']);
});

test('triangle cap and malformed vertex colors fail closed', () => {
  install(mesh({ indices: [0, 1, 2, 0, 1, 2] }));
  assert.throws(() => extractMeshGeometry({ maxTriangles: 1 }), /maxTriangles/);
  install(mesh({ vertexColors: [[1, 0, 0]] }));
  assert.throws(() => extractMeshGeometry(), /vertex color count/);
});

test('vertex-colored meshes expose world-space flat color evidence to region gates', () => {
  const colors = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  install(mesh({ matrix: translate(3, 2, 1), vertexColors: colors }));
  const result = extractMeshGeometry().meshes[0];
  assert.deepEqual(result.positions, [3, 2, 1, 4, 2, 1, 3, 3, 1]);
  assert.deepEqual(result.colors, colors.flat());
  assert.deepEqual(result.vertices[0], [3, 2, 1]);
});

test('failed fresh capture removes stale output; successful capture forwards the documented flags', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'img2-mesh-export-'));
  const output = join(directory, 'meshes.json');
  const argv = ['--url', 'http://127.0.0.1:5173', '--out', output,
    '--include', '^subject', '--exclude', 'studio', '--max-triangles', '99',
    '--ready-flag', 'MODEL_READY', '--viewer-handle', 'CUSTOM_VIEWER'];
  try {
    await writeFile(output, '{"meshes":[{"name":"old-stale-data"}]}');
    const brokenChromium = { async launch() { throw new Error('browser unavailable'); } };
    assert.equal(await main(argv, { chromium: brokenChromium }), 2);
    await assert.rejects(readFile(output, 'utf8'), { code: 'ENOENT' });

    const calls = [];
    let failEvaluate = false;
    const chromium = { async launch() {
      return {
        async newPage() {
          return {
            on() {},
            async goto() {},
            async waitForFunction(expr, arg) { calls.push({ expr, arg }); },
            async evaluate(_fn, options) {
              calls.push({ options });
              if (failEvaluate) throw new Error('incomplete capture');
              return { coordinateSpace: 'world', meshes: [{ name: 'subject', vertices: [[0, 0, 0]], indices: [0, 0, 0] }] };
            },
          };
        },
        async close() {},
      };
    } };
    assert.equal(await main(argv, { chromium }), 0);
    assert.equal(JSON.parse(await readFile(output, 'utf8')).meshes[0].name, 'subject');
    assert.ok(calls.some(item => item.arg === 'MODEL_READY'));
    // The shared preview signal must be the boolean true. Boolean('false')
    // is true in JavaScript and would otherwise certify an unready render.
    assert.ok(calls.some(item => item.expr ===
      '() => window.__IMG2THREEJS_READY__ === true'));
    assert.equal(calls.find(item => item.options)?.options?.maxTriangles, 99);
    assert.equal(calls.find(item => item.options)?.options?.viewerHandle, 'CUSTOM_VIEWER');
    failEvaluate = true;
    assert.equal(await main(argv, { chromium }), 2);
    await assert.rejects(readFile(output, 'utf8'), { code: 'ENOENT' });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
