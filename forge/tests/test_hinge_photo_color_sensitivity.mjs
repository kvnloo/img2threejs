import {test} from 'node:test';
import assert from 'node:assert/strict';
import {THRESHOLD_PAIRS,measureThresholdSensitivity} from './hinge_photo_color_sensitivity.mjs';

const pixels = (...triplets) => new Uint8ClampedArray(
  triplets.flatMap(([r,g,b]) => [r,g,b,255])
);

test('identical colors have identical segmentation across all nine thresholds',()=>{
  const ref = pixels([180,115,80],[115,115,115],[220,100,50]);
  const list = measureThresholdSensitivity(ref,ref);
  assert.equal(list.length,9);
  assert.deepEqual(list.map(x=>x.iou),Array(9).fill(1));
  assert.deepEqual(THRESHOLD_PAIRS[4],[13,22]);
});

test('a changed warm pixel reduces IoU instead of inventing a match',()=>{
  const ref = pixels([180,115,80],[115,115,115]);
  const altered = pixels([115,115,115],[220,115,80]);
  const [result] = measureThresholdSensitivity(ref,altered,[[13,22]]);
  assert.equal(result.referencePixels,1);
  assert.equal(result.renderedPixels,1);
  assert.equal(result.iou,0);
});

test('all-background and malformed buffers fail closed',()=>{
  const zero=pixels([5,5,5]);
  assert.throws(()=>measureThresholdSensitivity(zero,zero),/empty segmentation union/);
  assert.throws(()=>measureThresholdSensitivity(zero,new Uint8Array(0)),/RGBA buffers/);
  assert.throws(()=>measureThresholdSensitivity(zero,new Uint8Array(5)),/RGBA buffers/);
  assert.throws(()=>measureThresholdSensitivity(zero,zero,[[NaN,4]]),/invalid RG/);
  assert.throws(()=>measureThresholdSensitivity(zero,zero,[]),/1-40/);
});
