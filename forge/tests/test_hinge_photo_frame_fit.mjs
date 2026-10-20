import { test } from 'node:test';
import assert from 'node:assert/strict';
import { FIT_BOUNDS, FIT_STEPS, optimizeFraming } from './hinge_photo_frame_fit.mjs';

const quadratic = (goal, weighting = 1) => p => {
  const loss = (p.dx - goal.dx) ** 2 +
    (p.dy - goal.dy) ** 2 +
    weighting * (p.zoom - goal.zoom) ** 2;
  const score = Math.max(0, 1 - loss / 9);
  return { train: score, holdout: score * 0.95, full: score * 0.97 };
};

test('bounded 3-axis search converges on a known camera without changing inputs', () => {
  const start = { dx: 0, dy: 0, zoom: 1 };
  const goal = { dx: 0.52, dy: -0.32, zoom: 1.27 };
  const startCopy = { ...start };
  const found = optimizeFraming(quadratic(goal), {initial:start});
  assert.deepEqual(start,startCopy,'must never mutate authored camera');
  assert.ok(found.fittedMetrics.train > found.baseline.train, JSON.stringify(found));
  assert.ok(Math.abs(found.fitted.dx - goal.dx) <= 0.061);
  assert.ok(Math.abs(found.fitted.dy - goal.dy) <= 0.061);
  assert.ok(Math.abs(found.fitted.zoom - goal.zoom) <= 0.031);
  assert.ok(found.evaluations <= 37);
  assert.equal(found.attempts,12);
  assert.deepEqual(found.fitted, optimizeFraming(quadratic(goal)).fitted,
    'same source and schedule must yield identical camera');
});

test('a flat objective leaves the authored baseline unchanged', () => {
  const result = optimizeFraming(() => ({
    train:0.42, holdout:0.41, full:0.43
  }));
  assert.deepEqual(result.fitted,{dx:0,dy:0,zoom:1});
  assert.equal(result.fittedMetrics.train,0.42);
  assert.ok(result.evaluations <= result.budget);
});

test('bounded fitting clips candidate camera parameters', () => {
  const result = optimizeFraming(quadratic({
    dx:50,dy:-50,zoom:100
  }));
  assert.ok(result.fitted.dx <= FIT_BOUNDS.dx[1]);
  assert.ok(result.fitted.dy >= FIT_BOUNDS.dy[0]);
  assert.ok(result.fitted.zoom <= FIT_BOUNDS.zoom[1]);
  assert.ok(result.evaluations <= result.budget);
});

test('invalid budgets, camera settings and observations fail explicitly', () => {
  assert.throws(()=>optimizeFraming(null),/requires scoring callback/);
  assert.throws(()=>optimizeFraming(quadratic({dx:0,dy:0,zoom:1}),{
    steps:[{pan:0,zoom:0.1}]
  }),/positive and finite/);
  assert.throws(()=>optimizeFraming(quadratic({dx:0,dy:0,zoom:1}),{
    steps:FIT_STEPS,bounds:{...FIT_BOUNDS,zoom:[-1,5]}
  }),/invalid camera parameter/);
  assert.throws(()=>optimizeFraming(()=>({train:NaN,holdout:0.2,full:0.2})),
    /non-finite/);
  assert.throws(()=>optimizeFraming(()=>({train:0.2,holdout:Infinity,full:0.2})),
    /non-finite/);
});

test('bounded measurements cannot exceed their stated budget', () => {
  let invocations=0;
  const result=optimizeFraming(p=>{
    invocations++;
    return {train:p.zoom/2,holdout:p.dx + 0.5 > 0?0.2:0,full:0.4};
  });
  assert.ok(result.evaluations <= result.budget);
  assert.equal(invocations,result.evaluations,'cached duplicate candidates must not rerun');
  assert.equal(result.evaluations<=37,true);
});
