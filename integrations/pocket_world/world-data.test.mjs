import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { demoPixels, voxelize, validateWorld, tileHeight, exportThreeFactory, serializeWorld, deserializeWorld, previewWorldPixels } from './world-data.mjs';

test('deterministic presets produce RGBA without random or hidden image data', () => {
  for (const theme of ['sunset', 'forest', 'cosmic']) {
    const a = demoPixels(theme, 12);
    assert.equal(a.length, 12 * 12 * 4);
    assert.deepEqual(a, demoPixels(theme, 12));
    assert.ok(a.every(v => v >= 0 && v <= 255));
  }
  assert.notDeepEqual(demoPixels('forest', 12), demoPixels('cosmic', 12));
  assert.throws(() => demoPixels('missing'));
});

test('voxelizer uses pixel colors, smooths brightness and honors alpha', () => {
  const rgba = new Uint8ClampedArray(4 * 4 * 4);
  for (let i = 0; i < 16; i++) rgba.set([50, 100, 200, 255], i * 4);
  rgba.set([250, 0, 0, 0], 0);
  const data = voxelize(rgba, 4);
  assert.equal(data.visible[0], 0);
  assert.equal(data.colors[1], 0x3264c8);
  assert.ok(data.heights[1] > 0 && data.heights[1] < 255);
  assert.equal(validateWorld(data), data);
});

test('reject malformed worlds, oversized inputs, and unsafe relief', () => {
  assert.throws(() => voxelize([], 64));
  assert.throws(() => voxelize(new Uint8Array(4 * 4 * 4), 100));
  const data = voxelize(demoPixels('sunset', 8), 8);
  assert.throws(() => validateWorld({ ...data, colors: [-1] }));
  assert.throws(() => validateWorld({ ...data, heights: [...data.heights.slice(0, -1), Infinity] }));
  assert.throws(() => exportThreeFactory(data, NaN));
  assert.throws(() => tileHeight(100, -1));
  assert.ok(tileHeight(255, 2) > tileHeight(255, .5));
});

test('standalone export is deterministic, syntactically valid, and asset-free', () => {
  const data = voxelize(demoPixels('forest', 8), 8);
  const src = exportThreeFactory(data, 1.25);
  assert.equal(src, exportThreeFactory(data, 1.25));
  assert.match(src, /export function buildPocketWorld/);
  assert.match(src, /new THREE\.InstancedMesh/);
  assert.doesNotMatch(src, /fetch\(|\.glb|XMLHttpRequest|https?:\/\//);
  const check = spawnSync(process.execPath, ['--check', '--input-type=module'], { input: src, encoding: 'utf8' });
  assert.equal(check.status, 0, check.stderr);
  const redacted = { ...data, visible: Array(64).fill(0) };
  assert.match(exportThreeFactory(redacted), /null/);
});

test('path planner respects invisible gaps, endpoints and nearest spawn', async () => {
  const { findTilePath, nearestVisibleTile } = await import('./world-data.mjs');
  const data = voxelize(demoPixels('forest', 5), 5);
  assert.deepEqual(findTilePath(data, 12, 12), [12]);
  assert.deepEqual(findTilePath(data, 0, 4), [0, 1, 2, 3, 4]);
  const broken = { ...data, visible: data.visible.slice() };
  for (let i = 5; i < 10; i++) broken.visible[i] = 0;
  assert.deepEqual(findTilePath(broken, 0, 24), []);
  assert.deepEqual(findTilePath(broken, 7, 24), []);
  assert.equal(nearestVisibleTile(broken, 7), 2);
  assert.throws(() => findTilePath(broken, -1, 3), RangeError);
  assert.throws(() => findTilePath(broken, 0, 25), RangeError);
  assert.throws(() => nearestVisibleTile(broken, 25), RangeError);
  const empty = { ...data, visible: Array(25).fill(0) };
  assert.equal(nearestVisibleTile(empty, 12), -1);
  assert.deepEqual(findTilePath(empty, 0, 3), []);
});

test('A* paths have valid neighbors and optimal slope-aware cost', async () => {
  const { findTilePath } = await import('./world-data.mjs');
  let seed = 1097;
  const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  const side = 8;
  for (let trial = 0; trial < 60; trial++) {
    const data = voxelize(demoPixels('cosmic', side), side);
    data.visible = data.visible.map(() => Number(random() > .25));
    data.visible[0] = data.visible[63] = 1;
    data.heights = data.heights.map(() => Math.floor(random() * 256));
    const path = findTilePath(data, 0, 63);
    if (path.length) {
      assert.equal(path[0], 0);
      assert.equal(path.at(-1), 63);
      for (let i = 1; i < path.length; i++) {
        assert.ok(data.visible[path[i]]);
        assert.equal(Math.abs(path[i] % side - path[i - 1] % side) + Math.abs(Math.floor(path[i] / side) - Math.floor(path[i - 1] / side)), 1);
      }
    }
    const cost = new Array(64).fill(Infinity);
    const visited = new Set();
    cost[0] = 0;
    for (let iteration = 0; iteration < 64; iteration++) {
      let best = -1;
      for (let i = 0; i < 64; i++) {
        if (!visited.has(i) && (best === -1 || cost[i] < cost[best])) best = i;
      }
      if (best === -1 || !Number.isFinite(cost[best])) break;
      visited.add(best);
      const x = best % side, y = Math.floor(best / side);
      const neighbors = [y ? best - side : -1, x < side - 1 ? best + 1 : -1, y < side - 1 ? best + side : -1, x ? best - 1 : -1];
      for (const n of neighbors) if (n >= 0 && data.visible[n]) cost[n] = Math.min(cost[n], cost[best] + 1 + Math.abs(data.heights[n] - data.heights[best]) / 255 * 1.5);
    }
    const foundCost = path.reduce((sum, here, i) => i ? sum + 1 + Math.abs(data.heights[here] - data.heights[path[i - 1]]) / 255 * 1.5 : 0, 0);
    if (!Number.isFinite(cost[63])) assert.deepEqual(path, []);
    else assert.ok(Math.abs(foundCost - cost[63]) < 1e-8, `Trial ${trial} was suboptimal: got ${foundCost}, optimal ${cost[63]}`);
  }
});

test('generated factory runs against a minimal Three.js-compatible stub and preserves geometry', async () => {
  const { runInNewContext } = await import('node:vm');
  const data = voxelize(demoPixels('sunset', 4), 4);
  data.visible[1] = data.visible[8] = 0;
  const matrices = [], colors = [];
  class FakeGroup { constructor() { this.children = []; } add(item) { this.children.push(item); } }
  class FakeMesh {
    constructor(geometry, material, count) { this.geometry = geometry; this.material = material; this.count = count; this.instanceMatrix = {}; this.instanceColor = {}; }
    setMatrixAt(i, matrix) { matrices[i] = matrix; }
    setColorAt(i, color) { colors[i] = color.hex; }
  }
  class FakePosition { set(...coords) { this.coords = coords; } }
  class FakeObject { constructor() { this.position = new FakePosition(); this.scale = new FakePosition(); } updateMatrix() { this.matrix = { position: [...this.position.coords], scale: [...this.scale.coords] }; } }
  const THREE = {
    Group: FakeGroup, InstancedMesh: FakeMesh, Object3D: FakeObject,
    BoxGeometry: class { }, MeshStandardMaterial: class { },
    Color: class { setHex(hex) { this.hex = hex; return this; } },
  };
  const code = exportThreeFactory(data, 1.5)
    .replace("import * as THREE from 'three';", '')
    .replace('export function buildPocketWorld()', 'function buildPocketWorld()');
  const group = runInNewContext(`${code}\nbuildPocketWorld()`, { THREE });
  assert.equal(group.name, 'PocketWorld');
  assert.equal(group.children.length, 1);
  assert.equal(group.children[0].count, 14);
  assert.equal(group.children[0].instanceMatrix.needsUpdate, true);
  assert.equal(group.children[0].instanceColor.needsUpdate, true);
  const expectedCells = Array.from({ length: 16 }, (_, i) => i).filter(i => data.visible[i]);
  expectedCells.forEach((i, k) => {
    assert.equal(colors[k], data.colors[i]);
    assert.deepEqual(matrices[k].position, [i % 4 - 1.5, tileHeight(data.heights[i], 1.5) / 2, Math.floor(i / 4) - 1.5]);
    assert.deepEqual(matrices[k].scale, [1, tileHeight(data.heights[i], 1.5), 1]);
  });
});


test('world receipts round-trip numeric terrain and relief without original image bytes', () => {
  const data = voxelize(demoPixels('forest'));
  data.visible[3] = 0;
  const receipt = serializeWorld(data, 2.2);
  assert.equal(receipt, serializeWorld(data, 2.2));
  assert.doesNotMatch(receipt, /data:image|https?:|base64/i);
  const restored = deserializeWorld(receipt);
  assert.deepEqual(restored.data, data);
  assert.equal(restored.relief, 2.2);
  const preview = previewWorldPixels(restored.data);
  assert.equal(preview.length, 28 * 28 * 4);
  assert.equal(preview[3 * 4 + 3], 0);
  assert.equal(preview[2 * 4 + 3], 255);
  assert.equal(preview[4 * 4], (data.colors[4] >>> 16) & 255);
});

test('world receipts fail closed on malformed schema, relief, dimensions and size', () => {
  const data = voxelize(demoPixels('sunset'));
  const valid = JSON.parse(serializeWorld(data, 1));
  for (const fake of [
    { ...valid, kind: 'different' },
    { ...valid, version: 2 },
    { ...valid, relief: 9 },
    { ...valid, relief: null },
    { ...valid, relief: undefined },
    { ...valid, relief: '2' },
    { ...valid, world: { ...valid.world, size: 8 } },
    { ...valid, world: { ...valid.world, colors: [...data.colors.slice(0,-1), -1] } },
  ]) assert.throws(() => deserializeWorld(JSON.stringify(fake)), RangeError);
  assert.throws(() => deserializeWorld('{invalid'), SyntaxError);
  assert.throws(() => deserializeWorld(' '.repeat(128 * 1024 + 1)), RangeError);
  assert.throws(() => serializeWorld(voxelize(demoPixels('forest', 8))), RangeError);
  assert.throws(() => serializeWorld(data, Infinity), RangeError);
  assert.throws(() => previewWorldPixels(voxelize(demoPixels('forest', 8))), RangeError);
});
