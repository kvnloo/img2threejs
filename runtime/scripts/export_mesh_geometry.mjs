#!/usr/bin/env node
// Export visible Three.js BufferGeometry into the geometry gate's meshes.json.
// The preview exposes __IMG2THREEJS_MESH_ROOT__ or capture.getModelRoot().
import { mkdir, rename, rm, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Deliberately self-contained: Playwright serializes this function into the page.
// Do not reference imported modules or module-scoped helpers from here.
export function extractMeshGeometry({ maxVertices = 300_000, maxInstances = 1_000 } = {}) {
  const scope = typeof window === 'undefined' ? globalThis : window;
  const capture = scope.__IMG2THREEJS_CAPTURE__;
  const root = scope.__IMG2THREEJS_MESH_ROOT__
    ?? (typeof capture?.getModelRoot === 'function' ? capture.getModelRoot() : capture?.modelRoot);
  if (!root || typeof root !== 'object' || !Array.isArray(root.children)) {
    throw new Error('Preview must expose window.__IMG2THREEJS_MESH_ROOT__ (a Three.js Object3D)');
  }
  if (typeof root.updateWorldMatrix === 'function') root.updateWorldMatrix(true, true);
  else if (typeof root.updateMatrixWorld === 'function') root.updateMatrixWorld(true);

  const multiply = (left, right) => {
    const result = new Array(16);
    for (let col = 0; col < 4; col += 1) {
      for (let row = 0; row < 4; row += 1) {
        let sum = 0;
        for (let k = 0; k < 4; k += 1) sum += left[k * 4 + row] * right[col * 4 + k];
        result[col * 4 + row] = sum;
      }
    }
    return result;
  };
  const requireFinite = (values, description) => {
    if (!values.every(Number.isFinite)) throw new Error(`${description}: non-finite geometry or transform`);
    return values;
  };
  const meshes = [];
  let vertexBudgetUsed = 0;
  const walk = (node) => {
    if (node.visible === false) return;
    if (node.isMesh) {
      const name = String(node.name || node.userData?.componentId || `mesh-${meshes.length}`);
      const geometry = node.geometry;
      const position = geometry?.attributes?.position;
      const normal = geometry?.attributes?.normal;
      if (!position || !Number.isInteger(position.count) || position.count < 3) {
        throw new Error(`${name}: BufferGeometry position attribute is missing or invalid`);
      }
      if (!normal || normal.count !== position.count) {
        throw new Error(`${name}: BufferGeometry needs one vertex normal per position`);
      }
      if (node.isSkinnedMesh || node.morphTargetInfluences?.some((value) => Math.abs(value) > 1e-8)) {
        throw new Error(`${name}: bake skinned/morphed pose before mesh-gate export`);
      }
      const indexed = geometry.index;
      const count = indexed ? indexed.count : position.count;
      if (!Number.isInteger(count) || count < 3 || count % 3 !== 0) {
        throw new Error(`${name}: triangle index count must be a positive multiple of 3`);
      }
      const range = geometry.drawRange;
      if (range && (range.start !== 0 || (Number.isFinite(range.count) && range.count < count))) {
        throw new Error(`${name}: partial drawRange must be baked before mesh-gate export`);
      }
      const baseIndices = Array.from({ length: count }, (_, i) => indexed ? indexed.getX(i) : i);
      if (baseIndices.some((value) => !Number.isInteger(value) || value < 0 || value >= position.count)) {
        throw new Error(`${name}: triangle index out of range`);
      }
      const world = node.matrixWorld?.elements;
      if (!world || world.length !== 16) throw new Error(`${name}: missing 4x4 world transform`);
      const instanceCount = node.isInstancedMesh ? node.count : 1;
      if (!Number.isInteger(instanceCount) || instanceCount < 0 || instanceCount > maxInstances) {
        throw new Error(`${name}: invalid or over-budget instance count ${instanceCount}`);
      }
      const instanceArray = node.instanceMatrix?.array;
      if (node.isInstancedMesh && (!instanceArray || instanceArray.length < instanceCount * 16)) {
        throw new Error(`${name}: instance matrices are missing`);
      }
      for (let instance = 0; instance < instanceCount; instance += 1) {
        vertexBudgetUsed += position.count;
        if (vertexBudgetUsed > maxVertices) throw new Error(`mesh-gate export exceeds maxVertices=${maxVertices}`);
        const matrix = node.isInstancedMesh
          ? multiply(world, instanceArray.slice(instance * 16, (instance + 1) * 16))
          : Array.from(world);
        requireFinite(matrix, name);
        const [a, d, g, , b, e, h, , c, f, i] = matrix;
        const cof = [e * i - f * h, f * g - d * i, d * h - e * g,
          c * h - b * i, a * i - c * g, b * g - a * h,
          b * f - c * e, c * d - a * f, a * e - b * d];
        const determinant = a * cof[0] + b * cof[1] + c * cof[2];
        if (!Number.isFinite(determinant) || Math.abs(determinant) < 1e-12) {
          throw new Error(`${name}: singular world/instance transform`);
        }
        const vertices = [];
        const normals = [];
        for (let index = 0; index < position.count; index += 1) {
          const x = position.getX(index), y = position.getY(index), z = position.getZ(index);
          const px = matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12];
          const py = matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13];
          const pz = matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14];
          vertices.push(requireFinite([px, py, pz], name));
          const nx = normal.getX(index), ny = normal.getY(index), nz = normal.getZ(index);
          // Inverse-transpose (cofactor / determinant), necessary for non-uniform scale.
          const tx = (cof[0] * nx + cof[1] * ny + cof[2] * nz) / determinant;
          const ty = (cof[3] * nx + cof[4] * ny + cof[5] * nz) / determinant;
          const tz = (cof[6] * nx + cof[7] * ny + cof[8] * nz) / determinant;
          const magnitude = Math.hypot(tx, ty, tz);
          if (!Number.isFinite(magnitude) || magnitude < 1e-12) {
            throw new Error(`${name}: invalid transformed vertex normal`);
          }
          normals.push(requireFinite([tx / magnitude, ty / magnitude, tz / magnitude], name));
        }
        const indices = determinant < 0 ? [...baseIndices] : baseIndices;
        if (determinant < 0) {
          for (let index = 0; index < indices.length; index += 3) {
            [indices[index + 1], indices[index + 2]] = [indices[index + 2], indices[index + 1]];
          }
        }
        meshes.push({
          name: node.isInstancedMesh ? `${name}[${instance}]` : name,
          vertices, normals, indices,
        });
      }
    }
    for (const child of node.children || []) walk(child);
  };
  walk(root);
  if (meshes.length === 0) throw new Error('No visible triangulated meshes in the model root');
  return { coordinateSpace: 'world', meshes };
}

function parseArgs(argv) {
  const options = { timeoutMs: 30_000, maxVertices: 300_000, maxInstances: 1_000, headed: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--headed') { options.headed = true; continue; }
    const key = { '--url': 'url', '--out': 'out', '--timeout-ms': 'timeoutMs',
      '--max-vertices': 'maxVertices', '--max-instances': 'maxInstances' }[arg];
    if (!key || !argv[i + 1]) throw new Error(`unknown/missing argument: ${arg}`);
    options[key] = argv[++i];
  }
  if (!options.url || !options.out) throw new Error('usage: node runtime/scripts/export_mesh_geometry.mjs --url <preview> --out meshes.json');
  const protocol = new URL(options.url).protocol;
  if (!['http:', 'https:', 'file:'].includes(protocol)) throw new Error('preview URL must be http(s) or file');
  for (const key of ['timeoutMs', 'maxVertices', 'maxInstances']) {
    options[key] = Number(options[key]);
    if (!Number.isSafeInteger(options[key]) || options[key] < 1) throw new Error(`${key} must be a positive integer`);
  }
  return options;
}

export async function main(argv) {
  let browser;
  try {
    const options = parseArgs(argv);
    let chromium;
    try {
      ({ chromium } = await import('playwright'));
    } catch {
      throw new Error('Playwright not installed: install it in an isolated Node environment and run npx playwright install chromium');
    }
    browser = await chromium.launch({ headless: !options.headed });
    const page = await browser.newPage();
    const pageErrors = [];
    page.on('pageerror', (error) => pageErrors.push(String(error)));
    await page.goto(options.url, { waitUntil: 'domcontentloaded', timeout: options.timeoutMs });
    await page.waitForFunction('() => Boolean(window.__IMG2THREEJS_READY__)', null, { timeout: options.timeoutMs });
    const result = await page.evaluate(extractMeshGeometry, {
      maxVertices: options.maxVertices, maxInstances: options.maxInstances,
    });
    if (pageErrors.length) throw new Error(`preview JavaScript errors: ${pageErrors.join('; ')}`);
    const target = resolve(options.out);
    const temporary = `${target}.tmp-${process.pid}`;
    await mkdir(dirname(target), { recursive: true });
    try {
      await writeFile(temporary, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
      await rename(temporary, target);
    } finally {
      await rm(temporary, { force: true });
    }
    console.log(`exported ${result.meshes.length} mesh(es) to ${target}`);
    return 0;
  } catch (error) {
    console.error(`error: ${error.message}`);
    return 2;
  } finally {
    if (browser) await browser.close();
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  process.exitCode = await main(process.argv.slice(2));
}
