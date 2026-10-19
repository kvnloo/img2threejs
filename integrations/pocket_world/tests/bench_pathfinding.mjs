/** Optional deterministic pathfinding microbenchmark (no browser/asset dependencies).
 * Compares the heap planner against the prior Set-scan planner, validating
 * route identity before publishing measurements. Times depend on CI hardware.
 */
import { performance } from 'node:perf_hooks';
import { demoPixels, voxelize, findTilePath } from '../world-data.mjs';

function oldPath(data, start, goal) {
  const n = data.size, count = n * n;
  if (!data.visible[start] || !data.visible[goal]) return [];
  const cost = new Float64Array(count).fill(Infinity);
  const previous = new Int32Array(count).fill(-1);
  const settled = new Uint8Array(count);
  const frontier = new Set([start]);
  const heuristic = i => Math.abs(i % n - goal % n) + Math.abs(Math.floor(i / n) - Math.floor(goal / n));
  cost[start] = 0;
  while (frontier.size) {
    let current = -1, bestScore = Infinity;
    for (const i of frontier) {
      const score = cost[i] + heuristic(i);
      if (score < bestScore || (score === bestScore && i < current)) {
        current = i; bestScore = score;
      }
    }
    if (current === goal) {
      const path = [];
      for (let i = goal; i !== -1; i = previous[i]) path.push(i);
      return path.reverse();
    }
    frontier.delete(current);
    settled[current] = 1;
    const x = current % n, y = Math.floor(current / n);
    const neighbors = [y > 0 ? current - n : -1, x < n - 1 ? current + 1 : -1, y < n - 1 ? current + n : -1, x > 0 ? current - 1 : -1];
    for (const next of neighbors) {
      if (next < 0 || settled[next] || !data.visible[next]) continue;
      const candidate = cost[current] + 1 + Math.abs(data.heights[current] - data.heights[next]) / 255 * 1.5;
      if (candidate < cost[next]) {
        cost[next] = candidate;
        previous[next] = current;
        frontier.add(next);
      }
    }
  }
  return [];
}

function measure(fn, data, routes, loops) {
  const samples = [];
  for (let sample = 0; sample < 7; sample++) {
    const start = performance.now();
    for (let k = 0; k < loops; k++) {
      for (const [a, b] of routes) fn(data, a, b);
    }
    samples.push(performance.now() - start);
  }
  samples.sort((a, b) => a - b);
  return { medianMs: Number(samples[3].toFixed(3)),
           minMs: Number(samples[0].toFixed(3)),
           maxMs: Number(samples.at(-1).toFixed(3)) };
}

const results = [];
for (const size of [28, 64]) {
  const data = voxelize(demoPixels('forest', size), size);
  let seed = size * 8191;
  const random = () => ((seed = (1664525 * seed + 1013904223) >>> 0) / 2 ** 32);
  data.heights = data.heights.map(() => Math.floor(random() * 255));
  const last = size * size - 1;
  const routes = [[0, last], [size - 1, last - size + 1], [last, 0],
    [last - size + 1, size - 1], [Math.floor(size / 2), last]];
  for (const [a, b] of routes) {
    const before = oldPath(data, a, b);
    const after = findTilePath(data, a, b);
    if (JSON.stringify(after) !== JSON.stringify(before)) {
      throw new Error(`path changed at ${size}x${size}: ${a} -> ${b}`);
    }
  }
  // Warm both implementations before collecting CPU-local observations.
  for (let k = 0; k < 2; k++) for (const [a, b] of routes) {
    oldPath(data, a, b); findTilePath(data, a, b);
  }
  const loops = size === 28 ? 18 : 6;
  const baseline = measure(oldPath, data, routes, loops);
  const heap = measure(findTilePath, data, routes, loops);
  results.push({
    grid: `${size}x${size}`, routeCount: routes.length, loops,
    baseline, heap,
    speedup: Number((baseline.medianMs / heap.medianMs).toFixed(2)),
    source: 'Node CPU, synthetic data, same routes; not WebGL/mobile frame timing',
  });
}
console.log(JSON.stringify({
  benchmark: 'pocket-world-scout-paths', version: 1,
  node: process.version, parity: 'exact', results,
}, null, 2));
