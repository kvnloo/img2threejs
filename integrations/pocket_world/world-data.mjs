/** Deterministic, dependency-free image sampling for a playful voxel relief. */
export const GRID_SIZE = 28;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const byte = v => clamp(Math.round(v), 0, 255);

export function demoPixels(theme = 'sunset', size = GRID_SIZE) {
  if (!Number.isInteger(size) || size < 4 || size > 64) throw new RangeError('Invalid grid size');
  const schemes = {
    sunset: { sky: [37, 57, 122], land: [255, 141, 111], glow: [255, 219, 132] },
    forest: { sky: [24, 75, 94], land: [61, 172, 126], glow: [230, 223, 139] },
    cosmic: { sky: [37, 24, 91], land: [158, 80, 191], glow: [249, 153, 206] },
  };
  if (!(theme in schemes)) throw new RangeError('Unknown preset');
  const { sky, land, glow } = schemes[theme];
  const rgba = new Uint8ClampedArray(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const u = x / (size - 1), v = y / (size - 1);
      const ridge = 0.5 + 0.17 * Math.sin(u * 13 + v * 5) + 0.11 * Math.sin(u * 25 - v * 12);
      const coast = clamp((v - ridge) * 6 + .48, 0, 1);
      const sun = Math.exp(-(((u - .75) / .17) ** 2 + ((v - .28) / .18) ** 2) * 2.4);
      const twinkle = .05 * Math.sin(u * 42 + v * 12) * Math.cos(v * 26 - u * 7);
      const i = (y * size + x) * 4;
      for (let k = 0; k < 3; k++) {
        rgba[i + k] = byte(sky[k] * (1 - coast) + land[k] * coast + (glow[k] - sky[k]) * sun * (1 - coast) + twinkle * 100);
      }
      rgba[i + 3] = 255;
    }
  }
  return rgba;
}

export function voxelize(rgba, size = GRID_SIZE) {
  if (!Number.isInteger(size) || size < 4 || size > 64) throw new RangeError('Invalid grid size');
  if (!rgba || rgba.length !== size * size * 4) throw new RangeError('Expected square RGBA pixel grid');
  const luminance = new Float64Array(size * size);
  const colors = new Array(size * size);
  const heights = new Array(size * size);
  const visible = new Array(size * size);
  for (let i = 0; i < size * size; i++) {
    visible[i] = rgba[4 * i + 3] >= 32 ? 1 : 0;
    // Fully transparent source pixels may contain arbitrary RGB bytes. They
    // must not influence the relief or survive into a downloaded passport.
    const r = visible[i] ? byte(rgba[4 * i]) : 0;
    const g = visible[i] ? byte(rgba[4 * i + 1]) : 0;
    const b = visible[i] ? byte(rgba[4 * i + 2]) : 0;
    colors[i] = (r << 16) | (g << 8) | b;
    luminance[i] = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  }
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = y * size + x;
      let sum = 0, weight = 0;
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          const nx = x + dx, ny = y + dy;
          if (nx < 0 || ny < 0 || nx >= size || ny >= size) continue;
          const j = ny * size + nx;
          if (!visible[j]) continue;
          const w = dx === 0 && dy === 0 ? 4 : (dx === 0 || dy === 0 ? 2 : 1);
          sum += luminance[j] * w;
          weight += w;
        }
      }
      const blend = weight ? .77 * (sum / weight) + .23 * luminance[i] : 0;
      heights[i] = visible[i] ? byte(blend * 255) : 0;
    }
  }
  return { size, colors, heights, visible };
}

export function validateWorld(data) {
  if (!data || !Number.isInteger(data.size) || data.size < 4 || data.size > 64) throw new RangeError('Invalid world');
  const n = data.size ** 2;
  for (const [key, max] of [['colors', 0xffffff], ['heights', 255], ['visible', 1]]) {
    const arr = data[key];
    if (!Array.isArray(arr) || arr.length !== n || arr.some(v => !Number.isInteger(v) || v < 0 || v > max)) throw new RangeError(`Invalid ${key}`);
  }
  return data;
}

/** Normalize hidden terrain without changing the source or legacy receipt schema. */
function withoutHiddenPixels(data) {
  return {
    size: data.size,
    colors: data.colors.map((color, i) => data.visible[i] ? color : 0),
    heights: data.heights.map((height, i) => data.visible[i] ? height : 0),
    visible: data.visible.slice(),
  };
}

/** Pick a visible start tile, preferring tiles close to the requested location. */
export function nearestVisibleTile(data, index) {
  validateWorld(data);
  if (!Number.isInteger(index) || index < 0 || index >= data.size ** 2) throw new RangeError('Invalid tile');
  const x = index % data.size, y = Math.floor(index / data.size);
  let best = -1, distance = Infinity;
  for (let i = 0; i < data.visible.length; i++) {
    if (!data.visible[i]) continue;
    const d = (i % data.size - x) ** 2 + (Math.floor(i / data.size) - y) ** 2;
    if (d < distance) { best = i; distance = d; }
  }
  return best;
}

/** A small stable min-heap for pathfinding. Lower score, then lower tile ID wins.
 * Stale heap entries are skipped by the caller instead of requiring decrease-key.
 */
function heapPush(heap, entry) {
  let position = heap.length;
  heap.push(entry);
  while (position > 0) {
    const parent = (position - 1) >> 1;
    const candidate = heap[parent];
    if (candidate.score < entry.score ||
        (candidate.score === entry.score && candidate.index <= entry.index)) break;
    heap[position] = candidate;
    position = parent;
  }
  heap[position] = entry;
}

function heapPop(heap) {
  const first = heap[0];
  const last = heap.pop();
  if (heap.length > 0) {
    let position = 0;
    for (;;) {
      const left = position * 2 + 1;
      if (left >= heap.length) break;
      const right = left + 1;
      let child = left;
      if (right < heap.length) {
        const a = heap[right], b = heap[left];
        if (a.score < b.score || (a.score === b.score && a.index < b.index)) child = right;
      }
      const next = heap[child];
      if (next.score > last.score ||
          (next.score === last.score && next.index >= last.index)) break;
      heap[position] = next;
      position = child;
    }
    heap[position] = last;
  }
  return first;
}

/** Deterministic A* over visible tiles using a binary heap (O(E log V)).
 * Slope affects cost, not reachability. Equal scores preserve lower tile IDs.
 */
export function findTilePath(data, start, goal) {
  validateWorld(data);
  const n = data.size, count = n * n;
  if (![start, goal].every(i => Number.isInteger(i) && i >= 0 && i < count)) throw new RangeError('Invalid path endpoint');
  if (!data.visible[start] || !data.visible[goal]) return [];
  if (start === goal) return [start];
  const cost = new Float64Array(count).fill(Infinity);
  const previous = new Int32Array(count).fill(-1);
  const settled = new Uint8Array(count);
  const heuristic = i => Math.abs(i % n - goal % n) + Math.abs(Math.floor(i / n) - Math.floor(goal / n));
  const frontier = [];
  cost[start] = 0;
  heapPush(frontier, { index: start, score: heuristic(start), cost: 0 });
  while (frontier.length) {
    const nextEntry = heapPop(frontier);
    const current = nextEntry.index;
    if (settled[current] || nextEntry.cost !== cost[current]) continue;
    if (current === goal) {
      const path = [];
      for (let i = goal; i !== -1; i = previous[i]) path.push(i);
      return path.reverse();
    }
    settled[current] = 1;
    const x = current % n, y = Math.floor(current / n);
    const neighbors = [y > 0 ? current - n : -1, x < n - 1 ? current + 1 : -1, y < n - 1 ? current + n : -1, x > 0 ? current - 1 : -1];
    for (const next of neighbors) {
      if (next < 0 || settled[next] || !data.visible[next]) continue;
      const candidate = cost[current] + 1 + Math.abs(data.heights[current] - data.heights[next]) / 255 * 1.5;
      if (candidate < cost[next]) {
        cost[next] = candidate;
        previous[next] = current;
        heapPush(frontier, { index: next, score: candidate + heuristic(next), cost: candidate });
      }
    }
  }
  return [];
}

/** Add a 4-connected, slope-interpolated causeway between two visible tile anchors.
 * The terrain arrays are never mutated. Existing visible cells preserve their colors/heights;
 * only transparent cells along the deterministic orthogonal corridor become walkable.
 */
export function buildBridge(data, start, goal) {
  validateWorld(data);
  const n = data.size, total = n * n;
  if (![start, goal].every(i => Number.isInteger(i) && i >= 0 && i < total)) throw new RangeError('Invalid bridge endpoint');
  if (!data.visible[start] || !data.visible[goal]) throw new RangeError('Bridge anchors must be visible tiles');
  let x = start % n, y = Math.floor(start / n);
  const tx = goal % n, ty = Math.floor(goal / n);
  const dx = Math.abs(tx - x), dy = Math.abs(ty - y);
  const sx = Math.sign(tx - x), sy = Math.sign(ty - y);
  let nx = 0, ny = 0;
  const path = [start];
  // Choosing by normalized half-step distance keeps the corridor near the straight
  // chord without diagonal-only contacts that the four-neighbor scout cannot cross.
  while (x !== tx || y !== ty) {
    if (nx < dx && (ny === dy || (2 * nx + 1) * dy <= (2 * ny + 1) * dx)) { x += sx; nx++; }
    else { y += sy; ny++; }
    path.push(y * n + x);
  }
  const colors = data.colors.slice(), heights = data.heights.slice(), visible = data.visible.slice();
  const added = [];
  for (let step = 1; step < path.length - 1; step++) {
    const cell = path[step];
    if (visible[cell]) continue;
    visible[cell] = 1;
    colors[cell] = 0xc9a981; // code-authored timber; no texture or external asset
    heights[cell] = Math.round(data.heights[start] + (data.heights[goal] - data.heights[start]) * step / (path.length - 1));
    added.push(cell);
  }
  return { data: { size: n, colors, heights, visible }, path, added };
}

export function tileHeight(heightByte, relief = 1) {
  if (!Number.isFinite(relief) || relief < 0 || relief > 3) throw new RangeError('Relief must be 0..3');
  return .32 + Math.pow(heightByte / 255, 1.45) * 3.8 * relief;
}

/** Validate a compact treasure-hunt bookmark against the exact saved terrain.
 * A saved scout may have been moving; bookmarks record only its last completed tile.
 */
export function validateAdventure(data, adventure) {
  validateWorld(data);
  if (!adventure || Array.isArray(adventure) || typeof adventure !== 'object') {
    throw new RangeError('Invalid adventure bookmark');
  }
  const n = data.size * data.size;
  const isTile = i => Number.isInteger(i) && i >= 0 && i < n && data.visible[i] === 1;
  const visibleCount = data.visible.reduce((a, b) => a + b, 0);
  const scoutCell = adventure.scoutCell;
  if (visibleCount === 0 ? scoutCell !== -1 : !isTile(scoutCell)) {
    throw new RangeError('Invalid scout bookmark');
  }
  const beaconCells = adventure.beaconCells, collectedCells = adventure.collectedCells;
  if (!Array.isArray(beaconCells) || beaconCells.length !== Math.min(5, visibleCount) ||
      beaconCells.some(i => !isTile(i)) || new Set(beaconCells).size !== beaconCells.length) {
    throw new RangeError('Invalid beacon bookmarks');
  }
  if (!Array.isArray(collectedCells) || collectedCells.length > beaconCells.length ||
      collectedCells.some(i => !isTile(i) || !beaconCells.includes(i)) ||
      new Set(collectedCells).size !== collectedCells.length) {
    throw new RangeError('Invalid collected bookmarks');
  }
  return { scoutCell, beaconCells: [...beaconCells], collectedCells: [...collectedCells] };
}

/** Suggest a reachable uncollected beacon using the same slope-aware path cost as A*.
 * Paths are never fabricated across invisible cells; a blocked world returns null.
 */
export function nextBeaconRoute(data, scoutCell, beaconCells, collectedCells = []) {
  validateWorld(data);
  if (!Number.isInteger(scoutCell) || scoutCell < -1 || scoutCell >= data.visible.length ||
      (scoutCell >= 0 && !data.visible[scoutCell])) throw new RangeError('Invalid scout route');
  if (!Array.isArray(beaconCells) || !Array.isArray(collectedCells) ||
      beaconCells.some(i => !Number.isInteger(i) || i < 0 || i >= data.visible.length || !data.visible[i]) ||
      new Set(beaconCells).size !== beaconCells.length ||
      collectedCells.some(i => !beaconCells.includes(i))) throw new RangeError('Invalid beacon targets');
  if (scoutCell < 0) return null;
  const collected = new Set(collectedCells);
  const remaining = new Set(beaconCells.filter(target => !collected.has(target)));
  if (!remaining.size) return null;
  // One Dijkstra traversal finds the cheapest reachable treasure, rather than
  // running five independent A* searches over the same terrain and scout start.
  // Exact slope costs and tie-breaking match findTilePath/previous compass.
  const size = data.size, count = size * size;
  const cost = new Float64Array(count).fill(Infinity);
  const previous = new Int32Array(count).fill(-1);
  const settled = new Uint8Array(count);
  const frontier = [];
  cost[scoutCell] = 0;
  heapPush(frontier, { index: scoutCell, score: 0, cost: 0 });
  let bestTarget = -1, bestCost = Infinity;
  while (frontier.length) {
    const entry = heapPop(frontier);
    const current = entry.index;
    if (settled[current] || entry.cost !== cost[current]) continue;
    // Finish all reachable ties within tolerance before selecting by tile ID.
    if (bestTarget >= 0 && entry.cost > bestCost + 1e-9) break;
    if (remaining.has(current)) {
      if (bestTarget < 0 || entry.cost < bestCost - 1e-9 ||
          (Math.abs(entry.cost - bestCost) < 1e-9 && current < bestTarget)) {
        bestTarget = current;
        bestCost = entry.cost;
      }
      remaining.delete(current);
      if (!remaining.size) break;
    }
    settled[current] = 1;
    const x = current % size, y = Math.floor(current / size);
    const neighbors = [y > 0 ? current - size : -1, x < size - 1 ? current + 1 : -1,
      y < size - 1 ? current + size : -1, x > 0 ? current - 1 : -1];
    for (const next of neighbors) {
      if (next < 0 || settled[next] || !data.visible[next]) continue;
      const candidate = cost[current] + 1 + Math.abs(data.heights[current] - data.heights[next]) / 255 * 1.5;
      if (candidate < cost[next]) {
        cost[next] = candidate;
        previous[next] = current;
        heapPush(frontier, { index: next, score: candidate, cost: candidate });
      }
    }
  }
  if (bestTarget < 0) return null;
  const path = [];
  for (let i = bestTarget; i !== -1; i = previous[i]) path.push(i);
  path.reverse();
  return { target: bestTarget, path, steps: path.length - 1, cost: bestCost };
}

/** Legacy v1 terrain stays readable; new v2 receipts optionally preserve the adventure. */
export function serializeWorld(data, relief = 1, adventure = null) {
  validateWorld(data);
  if (data.size !== GRID_SIZE) throw new RangeError('Saved worlds must use the 28x28 grid');
  tileHeight(0, relief);
  const receipt = {
    kind: 'img2threejs-pocket-world',
    version: adventure === null ? 1 : 2,
    relief,
    world: withoutHiddenPixels(data),
  };
  if (adventure !== null) receipt.adventure = validateAdventure(data, adventure);
  return JSON.stringify(receipt);
}

/** Refuse schema drift, oversized receipts and invalid numeric terrain/bookmarks. */
export function deserializeWorld(text) {
  if (typeof text !== 'string' || text.length > 128 * 1024) throw new RangeError('World receipt too large or not text');
  const receipt = JSON.parse(text);
  if (!receipt || Array.isArray(receipt) || receipt.kind !== 'img2threejs-pocket-world' ||
      (receipt.version !== 1 && receipt.version !== 2)) throw new RangeError('Unsupported Pocket World receipt');
  if (typeof receipt.relief !== 'number' || !Number.isFinite(receipt.relief) || receipt.relief < 0 || receipt.relief > 3) {
    throw new RangeError('Invalid saved world relief');
  }
  const data = withoutHiddenPixels(validateWorld(receipt.world));
  if (data.size !== GRID_SIZE) throw new RangeError('Saved worlds must use the 28x28 grid');
  tileHeight(0, receipt.relief);
  const adventure = receipt.version === 2 ? validateAdventure(data, receipt.adventure) : null;
  return { data, relief: receipt.relief, adventure };
}

/** The saved numeric terrain is enough to preview it without recovering the source image. */
export function previewWorldPixels(data) {
  validateWorld(data);
  if (data.size !== GRID_SIZE) throw new RangeError('Preview must be 28x28');
  const rgba = new Uint8ClampedArray(data.colors.length * 4);
  for (let i = 0; i < data.colors.length; i++) {
    const color = data.visible[i] ? data.colors[i] : 0;
    rgba[4 * i] = (color >>> 16) & 255;
    rgba[4 * i + 1] = (color >>> 8) & 255;
    rgba[4 * i + 2] = color & 255;
    rgba[4 * i + 3] = data.visible[i] ? 255 : 0;
  }
  return rgba;
}

/** Produces a standalone, inspectable ES module; no source image or remote asset is required. */
export function exportThreeFactory(data, relief = 1) {
  validateWorld(data);
  tileHeight(0, relief);
  const packed = data.colors.map((color, i) => data.visible[i] ? [color, data.heights[i]] : null);
  return `// Pocket World: experimental stylized pixel relief, not measured 3D reconstruction.\n` +
    `import * as THREE from 'three';\n` +
    `export function buildPocketWorld() {\n` +
    `  const size = ${data.size};\n` +
    `  const relief = ${Number(relief)};\n` +
    `  const pixels = ${JSON.stringify(packed)};\n` +
    `  const group = new THREE.Group();\n` +
    `  group.name = 'PocketWorld';\n` +
    `  const count = pixels.reduce((n, p) => n + Number(p !== null), 0);\n` +
    `  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(0.94, 1, 0.94), new THREE.MeshStandardMaterial({ roughness: .88, metalness: .02 }), count);\n` +
    `  mesh.name = 'PixelRelief';\n` +
    `  const dummy = new THREE.Object3D();\n` +
    `  const color = new THREE.Color();\n` +
    `  let index = 0;\n` +
    `  for (let i = 0; i < pixels.length; i++) {\n` +
    `    const p = pixels[i]; if (p === null) continue;\n` +
    `    const height = .32 + Math.pow(p[1] / 255, 1.45) * 3.8 * relief;\n` +
    `    dummy.position.set((i % size) - (size - 1) / 2, height / 2, Math.floor(i / size) - (size - 1) / 2);\n` +
    `    dummy.scale.set(1, height, 1); dummy.updateMatrix();\n` +
    `    mesh.setMatrixAt(index, dummy.matrix);\n` +
    `    mesh.setColorAt(index, color.setHex(p[0])); index++;\n` +
    `  }\n` +
    `  mesh.instanceMatrix.needsUpdate = true;\n` +
    `  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;\n` +
    `  group.add(mesh);\n` +
    `  return group;\n` +
    `}\n`;
}
