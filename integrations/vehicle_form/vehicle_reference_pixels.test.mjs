import test from 'node:test';
import assert from 'node:assert/strict';
import { STATIONS, VIEW, pixelColumn, referencePixelColumn, worldX, widthFromPixelColumn, referenceTableFromColumns } from './vehicle_reference_pixels.mjs';

function column(upper = 10, lower = 20) {
  const data = new Uint8Array(VIEW.height * 4);
  for (let y = 0; y < VIEW.height; y++) {
    const offset = 4 * y;
    const green = y >= upper && y <= lower;
    data.set(green ? [40, 220, 90, 255] : [20, 30, 45, 255], offset);
  }
  return data;
}

test('top-down camera projects transformed vehicle X stations into stable pixel columns', () => {
  assert.deepEqual(STATIONS.map(({localX}) => pixelColumn(worldX(localX))), [300, 425, 550, 675, 800]);
  assert.deepEqual(STATIONS.map((_, i) => referencePixelColumn(i)), [302, 425, 550, 675, 798]);
});

test('pixel threshold returns actual silhouette thickness in orthographic world units', () => {
  const measured = widthFromPixelColumn(column(100, 179));
  assert.ok(Math.abs(measured.width - 0.8) < 1e-12);
  assert.equal(measured.bodyPixels, 80);
  assert.ok(Math.abs(measured.centerZ + 1.0) < 1e-12,
    'pixel-centered column must reconstruct world Z in the locked up=-Z camera');
});

test('reference pixel columns distinguish equal-width sideways shifts', () => {
  const aligned = widthFromPixelColumn(column(220, 259));
  const shifted = widthFromPixelColumn(column(245, 284));
  assert.equal(aligned.width, shifted.width);
  assert.ok(Math.abs(aligned.centerZ) < 1e-12);
  assert.ok(Math.abs(shifted.centerZ - 0.25) < 1e-12);
});

test('empty or bad image evidence fails closed', () => {
  const blank = column(500, 600);
  assert.throws(() => widthFromPixelColumn(blank), /no measurable/);
  assert.throws(() => widthFromPixelColumn([0, 0, 0]), /invalid image column/);
  assert.throws(() => pixelColumn(5000), /outside image/);
});

test('reference tables are measured from pixel columns and require provenance', () => {
  const pixels = [column(100,159), column(100,199), column(100,179), column(100,199), column(100,149)];
  const report = referenceTableFromColumns(pixels, 'synthetic Three.js reference image sha256=fixture');
  assert.deepEqual(report.stations.map(r => Math.round(r.referenceWidth*100)), [60, 100, 80, 100, 50]);
  assert.equal(report.stations.length, 5);
  assert.equal(report.reference.kind, 'measured-top-view');
  assert.equal(report.maxNormalizedCenterError, 0.08);
  assert.deepEqual(report.stations.map(r => Math.round(r.referenceCenterZ * 100)),
    [-110, -90, -100, -90, -115]);
  assert.throws(() => referenceTableFromColumns(pixels, ''), /provenance/);
  assert.throws(() => referenceTableFromColumns(pixels.slice(1), 'fixture'), /every vehicle station/);
});
