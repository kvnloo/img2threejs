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
    const r = byte(rgba[4 * i]), g = byte(rgba[4 * i + 1]), b = byte(rgba[4 * i + 2]);
    colors[i] = (r << 16) | (g << 8) | b;
    visible[i] = rgba[4 * i + 3] >= 32 ? 1 : 0;
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
      heights[i] = byte(blend * 255);
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

export function tileHeight(heightByte, relief = 1) {
  if (!Number.isFinite(relief) || relief < 0 || relief > 3) throw new RangeError('Relief must be 0..3');
  return .32 + Math.pow(heightByte / 255, 1.45) * 3.8 * relief;
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
