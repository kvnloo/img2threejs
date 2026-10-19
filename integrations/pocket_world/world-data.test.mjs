import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { demoPixels, voxelize, validateWorld, tileHeight, exportThreeFactory } from './world-data.mjs';

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
