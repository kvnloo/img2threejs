/** Deterministic, bounded 2D camera-framing coordinate descent.
 * Research-only: matches a binary silhouette in one reference image;
 * never edits geometry, folds, materials, or the core camera solver.
 */
export const FIT_STEPS = Object.freeze([
  Object.freeze({ pan: 0.48, zoom: 0.24 }),
  Object.freeze({ pan: 0.24, zoom: 0.12 }),
  Object.freeze({ pan: 0.12, zoom: 0.06 }),
  Object.freeze({ pan: 0.06, zoom: 0.03 }),
]);
export const FIT_BOUNDS = Object.freeze({
  dx: [-1.5, 1.5], dy: [-1.5, 1.5], zoom: [0.65, 1.6],
});
const AXES = Object.freeze(['dx', 'dy', 'zoom']);

export function optimizeFraming(evaluate, {
  initial = { dx: 0, dy: 0, zoom: 1 },
  steps = FIT_STEPS, bounds = FIT_BOUNDS,
} = {}) {
  if (typeof evaluate !== 'function' || !Array.isArray(steps) || steps.length < 1 ||
      steps.length > 10) {
    throw new TypeError('requires scoring callback and 1-10 finite step schedules');
  }
  const params = { ...initial };
  for (const axis of AXES) {
    const limit = bounds[axis], x = params[axis];
    if (!Array.isArray(limit) || limit.length !== 2 ||
        !limit.every(Number.isFinite) || limit[0] >= limit[1] ||
        !Number.isFinite(x) || x < limit[0] || x > limit[1] ||
        (axis === 'zoom' && limit[0] <= 0)) {
      throw new RangeError('invalid camera parameter bounds or initial value: ' + axis);
    }
  }
  for (const step of steps) {
    if (!step || !Number.isFinite(step.pan) || !Number.isFinite(step.zoom) ||
        step.pan <= 0 || step.zoom <= 0) {
      throw new RangeError('camera-fitting steps must be positive and finite');
    }
  }

  let calls = 0;
  const attempts = [];
  const cache = new Map();
  const score = candidate => {
    const key = AXES.map(axis => candidate[axis].toFixed(9)).join('/');
    if (cache.has(key)) return cache.get(key);
    const measurement = evaluate({ ...candidate });
    if (!measurement || !Number.isFinite(measurement.train) ||
        !Number.isFinite(measurement.holdout) || !Number.isFinite(measurement.full) ||
        [measurement.train, measurement.holdout, measurement.full].some(x => x < 0 || x > 1)) {
      throw new Error('frame scorer returned non-finite or out-of-range IoU');
    }
    calls++;
    cache.set(key, measurement);
    return measurement;
  };
  let winner = score(params);
  const baseline = { ...winner };
  for (const step of steps) {
    for (const axis of AXES) {
      const increment = axis === 'zoom' ? step.zoom : step.pan;
      let bestParams = { ...params };
      let bestScore = winner;
      for (const direction of [-1, 0, 1]) {
        const v = Math.max(bounds[axis][0], Math.min(bounds[axis][1],
          params[axis] + direction * increment));
        const candidate = { ...params, [axis]: Math.round(v * 1e9) / 1e9 };
        const next = score(candidate);
        // Stable and conservative: never accept score-tied geometry changes.
        if (next.train > bestScore.train + 1e-9) {
          bestParams = candidate;
          bestScore = next;
        }
      }
      Object.assign(params, bestParams);
      winner = bestScore;
      attempts.push({ axis, step: increment, bestTrain: winner.train });
    }
  }
  return {
    initial: { ...initial }, fitted: { ...params },
    baseline, fittedMetrics: { ...winner },
    evaluations: calls, attempts: attempts.length,
    budget: 1 + steps.length * AXES.length * 3,
    trainMetric: 'checkerboard-tile in-frame mask IoU',
    holdoutMetric: 'complementary checkerboard-tile in-frame mask IoU',
    constraints: 'pan and orthographic zoom only; same plan for both hinge variants',
    caveat: 'One photograph with spatially correlated train/holdout pixels; not independent scene validation',
  };
}
