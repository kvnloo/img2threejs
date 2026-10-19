import test from 'node:test';
import assert from 'node:assert/strict';
import { collectMeshGeometry, main } from './export_mesh_geometry.mjs';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const attr = rows => ({ count: rows.length, getX: i => rows[i][0], getY: i => rows[i][1], getZ: i => rows[i][2] });
const identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
function mesh(name = 'triangle', options = {}) {
  const positions = attr([[0, 0, 0], [1, 0, 0], [0, 1, 0]]);
  const normal = attr([[0, 0, 1], [0, 0, 1], [0, 0, 1]]);
  const entries = { position: positions, normal };
  const index = options.unindexed ? null : { count: 3, getX: i => i };
  return { name, isMesh: true, visible: true, matrixWorld: { elements: options.matrix || identity },
    geometry: { index, drawRange: options.drawRange, getAttribute: key => entries[key] }, ...options };
}
function capture(meshes, options) {
  const scene = { updateMatrixWorld() {}, traverse(visitor) { for (const item of meshes) visitor(item); } };
  globalThis.window = { __IMG2THREEJS_VIEWER__: { scene } };
  try { return collectMeshGeometry(options); } finally { delete globalThis.window; }
}

test('exports indexed and non-indexed triangle geometry in gate-compatible shape', () => {
  const report = capture([mesh('indexed'), mesh('unindexed', { unindexed: true })]);
  assert.equal(report.incomplete, false);
  assert.deepEqual(report.meshes.map(m => m.indices), [[0, 1, 2], [0, 1, 2]]);
  assert.equal(report.meshes[0].normals.length, 3);
  assert.equal(report.coordinateSpace, 'world');
});

test('uses world-space positions and inverse-transpose normals', () => {
  const matrix = [2, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 1, 0, 3, 4, 5, 1];
  const m = mesh('scaled', { matrix });
  m.geometry.getAttribute = key => key === 'position' ? attr([[0, 0, 0], [1, 0, 0], [0, 1, 0]]) : attr([[1, 1, 0], [1, 1, 0], [1, 1, 0]]);
  const item = capture([m]).meshes[0];
  assert.deepEqual(item.vertices, [[3, 4, 5], [5, 4, 5], [3, 4.5, 5]]);
  assert.ok(Math.abs(item.normals[0][0] - 0.24253562503633297) < 1e-12);
  assert.ok(Math.abs(item.normals[0][1] - 0.9701425001453319) < 1e-12);
});

test('filters are explicit and do not create a false incomplete flag', () => {
  const result = capture([mesh('body'), mesh('hidden')], { include: '^body$' });
  assert.deepEqual(result.meshes.map(x => x.name), ['body']);
  assert.deepEqual(result.skipped, [{ name: 'hidden', reason: 'include-filter' }]);
  assert.equal(result.incomplete, false);
});

test('parent-hidden meshes are omitted from geometry evidence', () => {
  const result = capture([mesh('masked', { parent: { visible: false } })]);
  assert.equal(result.meshes.length, 0);
  assert.deepEqual(result.skipped, [{ name: 'masked', reason: 'hidden' }]);
});

test('unsupported and over-budget geometry fails closed with reasons', () => {
  const result = capture([mesh('instance', { isInstancedMesh: true }), mesh('deform', { isSkinnedMesh: true }),
    mesh('large')], { maxTriangles: 0 });
  assert.equal(result.meshes.length, 0);
  assert.equal(result.incomplete, true);
  assert.deepEqual(result.skipped.map(x => x.reason), [
    'unsupported-deformed-or-instanced', 'unsupported-deformed-or-instanced', 'triangle-cap']);
});

test('morphs, partial draws, and singular transforms are never passed as captured geometry', () => {
  const result = capture([mesh('morph', { morphTargetInfluences: [0.1] }),
    mesh('partial', { drawRange: { start: 1, count: 3 } }),
    mesh('singular', { matrix: new Array(16).fill(0) })]);
  assert.equal(result.incomplete, true);
  assert.deepEqual(result.skipped.map(x => x.reason), [
    'active-morph-target', 'partial-draw-range', 'singular-world-transform']);
});

test('missing viewer errors and help works without Playwright', async () => {
  assert.throws(() => collectMeshGeometry(), /window is not defined/);
  assert.equal(await main(['--help']), 0);
  assert.equal(await main(['--url', 'file:///etc/passwd', '--out', 'bad.json']), 2);
  assert.equal(await main(['--url', 'http://localhost', '--out', 'bad.json', '--include', '[']), 2);
});

test('CLI invalidates stale evidence and writes partial captures separately', () => {
  const root = mkdtempSync(join(tmpdir(), 'img2-mesh-export-'));
  try {
    const moduleDir = join(root, 'node_modules', 'playwright');
    mkdirSync(moduleDir, { recursive: true });
    writeFileSync(join(moduleDir, 'index.js'), [
      'exports.chromium = { launch: async () => ({',
      '  newPage: async () => ({ goto: async () => {}, waitForFunction: async () => {},',
      '    evaluate: async () => ({ meshes: [{ name: "fixture", vertices: [[0,0,0]], indices: [0,0,0] }],',
      '      skipped: process.env.PARTIAL ? [{ name: "another", reason: "triangle-cap" }] : [],',
      '      incomplete: Boolean(process.env.PARTIAL) }) }),',
      '  close: async () => {}',
      '}) };',
    ].join('\n'));
    const out = join(root, 'meshes.json');
    const cli = fileURLToPath(new URL('./export_mesh_geometry.mjs', import.meta.url));
    const run = partial => spawnSync(process.execPath, [cli, '--url', 'http://localhost:1234', '--out', out], {
      cwd: root, encoding: 'utf8', env: { ...process.env, IMG2THREEJS_SHOWCASE_ROOT: root, PARTIAL: partial ? '1' : '' },
    });
    assert.equal(run(false).status, 0);
    assert.equal(JSON.parse(readFileSync(out, 'utf8')).meshes.length, 1);
    const failed = run(true);
    assert.equal(failed.status, 2, failed.stderr);
    assert.equal(existsSync(out), false, 'old meshes.json must not survive a failed capture');
    assert.equal(JSON.parse(readFileSync(out + '.incomplete.json', 'utf8')).incomplete, true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
