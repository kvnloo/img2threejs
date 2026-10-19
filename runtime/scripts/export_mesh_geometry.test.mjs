import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { extractMeshGeometry } from './export_mesh_geometry.mjs';

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
  indices = [0, 1, 2], matrix = identity } = {}) {
  return {
    isMesh: true, name, visible: true, children: [],
    matrixWorld: { elements: matrix },
    geometry: {
      attributes: { position: attribute(vertices), normal: vertexNormals && attribute(vertexNormals) },
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
