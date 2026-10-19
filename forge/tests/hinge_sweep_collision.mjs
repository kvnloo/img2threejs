/** Research-only OBB narrow-phase for rigid box primitives emitted by img2threejs.
 *
 * Tests collision along a sampled fold sweep; not continuous collision detection,
 * not applicable to skinned, sheared, or non-box mesh geometry.
 * No new production dependencies or undocumented gate claims.
 */
import * as THREE from 'three';

const BASIS = [
  new THREE.Vector3(1, 0, 0),
  new THREE.Vector3(0, 1, 0),
  new THREE.Vector3(0, 0, 1),
];

export function readBox(mesh) {
  if (!mesh?.isMesh || mesh.geometry?.type !== 'BoxGeometry') {
    throw new TypeError('sweep OBB detector supports Three.js BoxGeometry meshes only');
  }
  mesh.updateWorldMatrix(true, false);
  if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
  const bounds = mesh.geometry.boundingBox;
  if (!bounds || bounds.isEmpty()) throw new Error('empty box bounds');
  const center = bounds.getCenter(new THREE.Vector3()).applyMatrix4(mesh.matrixWorld);
  const scale = new THREE.Vector3();
  const rotation = new THREE.Quaternion();
  const translation = new THREE.Vector3();
  mesh.matrixWorld.decompose(translation, rotation, scale);
  const half = bounds.getSize(new THREE.Vector3()).multiplyScalar(0.5);
  half.multiply(new THREE.Vector3(Math.abs(scale.x), Math.abs(scale.y), Math.abs(scale.z)));
  const axes = BASIS.map(axis => axis.clone().applyQuaternion(rotation).normalize());
  const matrixAxes = BASIS.map(axis => axis.clone().transformDirection(mesh.matrixWorld));
  for (let i = 0; i < 3; i++) {
    if (!axes[i].toArray().every(Number.isFinite) || !Number.isFinite(half.getComponent(i)) ||
        half.getComponent(i) <= 0 || axes[i].distanceTo(matrixAxes[i]) > 1e-5) {
      throw new Error('non-rigid or nonfinite box transform');
    }
  }
  // Guard world-matrix shear: projecting a sheared parallelepiped as an OBB
  // would be silently unsound. The generator bakes dimensions into vertices.
  for (let i = 0; i < 3; i++) for (let j = i + 1; j < 3; j++) {
    if (Math.abs(matrixAxes[i].dot(matrixAxes[j])) > 1e-5) {
      throw new Error('sheared box is not supported');
    }
  }
  if (!center.toArray().every(Number.isFinite)) throw new Error('nonfinite center');
  return { center, axes, half: [half.x, half.y, half.z] };
}

/** Returns signed overlap along all 15 SAT directions.
 * positive > eps means volume penetration; <= eps means contact/separation.
 * For thin panels the minimum overlap is intentionally small; do not
 * reinterpret it as a continuous-time swept volume or impact force.
 */
export function boxPenetration(meshA, meshB, eps = 1e-7) {
  if (!Number.isFinite(eps) || eps < 0) throw new RangeError('epsilon must be finite nonnegative');
  const a = readBox(meshA), b = readBox(meshB);
  const candidateAxes = [
    ...a.axes, ...b.axes,
    ...a.axes.flatMap(x => b.axes.map(y => x.clone().cross(y)))
  ];
  const delta = b.center.clone().sub(a.center);
  let minimum = Infinity;
  let testedAxes = 0;
  for (const candidate of candidateAxes) {
    const lengthSq = candidate.lengthSq();
    if (lengthSq < 1e-12) continue; // parallel cross axis: ill-conditioned
    const direction = candidate.clone().divideScalar(Math.sqrt(lengthSq));
    const ra = a.axes.reduce((sum, axis, i) =>
      sum + a.half[i] * Math.abs(axis.dot(direction)), 0);
    const rb = b.axes.reduce((sum, axis, i) =>
      sum + b.half[i] * Math.abs(axis.dot(direction)), 0);
    const depth = ra + rb - Math.abs(delta.dot(direction));
    if (!Number.isFinite(depth)) throw new Error('nonfinite projection');
    testedAxes++;
    minimum = Math.min(minimum, depth);
    if (depth <= eps) return { penetrating: false, overlap: depth, testedAxes };
  }
  if (testedAxes < 3) throw new Error('invalid box axes');
  return { penetrating: true, overlap: minimum, testedAxes };
}

export function sampleFold(joint, a, b, anglesDeg, eps = 1e-7) {
  if (!joint?.isObject3D || !Array.isArray(anglesDeg) || anglesDeg.length === 0) {
    throw new TypeError('expected joint and nonempty angle sample array');
  }
  const original = joint.rotation.y;
  const samples = [];
  try {
    for (const angle of anglesDeg) {
      if (!Number.isFinite(angle)) throw new RangeError('nonfinite sweep angle');
      joint.rotation.y = THREE.MathUtils.degToRad(angle);
      joint.updateWorldMatrix(true, true);
      const result = boxPenetration(a, b, eps);
      samples.push({ degrees: angle, penetrating: result.penetrating,
        overlap: result.overlap, testedAxes: result.testedAxes });
    }
  } finally {
    joint.rotation.y = original;
    joint.updateWorldMatrix(true, true);
  }
  return {
    samples,
    firstCollision: samples.find(sample => sample.penetrating) ?? null,
    collisionSamples: samples.filter(sample => sample.penetrating).length,
    resolutionDeg: anglesDeg.length > 1 ?
      Math.max(...anglesDeg.slice(1).map((v, i) => Math.abs(v - anglesDeg[i]))) : null,
    note: 'sampled rigid OBB collisions only; intervals between samples and mesh deformation untested',
  };
}

/** Conservative adaptive folding check for a static obstacle and one rigid box.
 *
 * An interval is called 'certified-clear' ONLY when a separating plane at
 * its midpoint has more free space than the greatest possible displacement
 * of any moving-box vertex before either endpoint. The displacement bound is
 * radiusFromPivot * angularHalfWidthRadians (arc length >= chord length).
 *
 * If the bound cannot be established within the supplied depth/evaluation
 * budget, status is 'unresolved' rather than 'clear'. An overlap found at any
 * evaluated angle returns 'collision'. This is a bounded research tool,
 * not a general continuous collision detector or a production quality gate.
 */
export function certifyFoldSweep(joint, moving, obstacle, startDeg, endDeg, {
  eps = 1e-7, maxDepth = 16, maxChecks = 4096,
} = {}) {
  if (!joint?.isObject3D || !moving?.isMesh || !obstacle?.isMesh) {
    throw new TypeError('a joint and two meshes are required');
  }
  if (![startDeg, endDeg].every(Number.isFinite)) {
    throw new RangeError('start and end angles must be finite');
  }
  if (!Number.isFinite(eps) || eps < 0 ||
      !Number.isInteger(maxDepth) || maxDepth < 0 || maxDepth > 24 ||
      !Number.isInteger(maxChecks) || maxChecks < 3 || maxChecks > 100000) {
    throw new RangeError('invalid epsilon, depth or check budget');
  }
  const descendantOf = (child, ancestor) => {
    for (let node = child; node; node = node.parent) if (node === ancestor) return true;
    return false;
  };
  if (!descendantOf(moving, joint) || descendantOf(obstacle, joint)) {
    throw new Error('moving must descend from the joint; obstacle must stay outside its subtree');
  }
  if (Math.abs(joint.rotation.x) > 1e-10 || Math.abs(joint.rotation.z) > 1e-10) {
    throw new Error('only single-axis joint Y rotations are supported');
  }

  // A parent world matrix which distorts the rotation circle is unsupported.
  // Uniform scale + an orthonormal frame preserves a circle and provides a
  // sound Euclidean arc-distance bound. No silently inferred physics.
  joint.updateWorldMatrix(true, true);
  const parentMatrix = joint.parent?.matrixWorld ?? new THREE.Matrix4();
  const e = parentMatrix.elements;
  const columns = [
    new THREE.Vector3(e[0], e[1], e[2]),
    new THREE.Vector3(e[4], e[5], e[6]),
    new THREE.Vector3(e[8], e[9], e[10]),
  ];
  const lengths = columns.map(col => col.length());
  const mean = lengths.reduce((a, b) => a + b, 0) / 3;
  if (!Number.isFinite(mean) || mean < 1e-12 ||
      lengths.some(l => !Number.isFinite(l) || Math.abs(l - mean) > mean * 1e-6) ||
      columns.some((v, i) => columns.some((w, j) =>
        i !== j && Math.abs(v.dot(w)) > mean * mean * 1e-6))) {
    throw new Error('joint parent frame must have uniform scale and no shear');
  }

  const original = joint.rotation.y;
  const probeCache = new Map();
  const unresolved = [];
  let certifiedIntervals = 0;
  let maxVisitedDepth = 0;
  let collision = null;
  function evaluate(degrees) {
    if (probeCache.has(degrees)) return probeCache.get(degrees);
    if (probeCache.size >= maxChecks) return null;
    joint.rotation.y = THREE.MathUtils.degToRad(degrees);
    joint.updateWorldMatrix(true, true);
    const sat = boxPenetration(moving, obstacle, eps);
    const box = readBox(moving);
    const pivot = joint.getWorldPosition(new THREE.Vector3());
    // Every box point lies within this sphere around the pivot. This loose
    // bound is deliberately conservative for narrow or offset panels.
    const radius = box.center.distanceTo(pivot) +
      box.half[0] + box.half[1] + box.half[2];
    if (!Number.isFinite(radius)) throw new Error('nonfinite swept radius');
    const result = { degrees, radius, overlap: sat.overlap,
      penetrating: sat.penetrating };
    probeCache.set(degrees, result);
    return result;
  }
  function interval(lo, hi, depth) {
    maxVisitedDepth = Math.max(maxVisitedDepth, depth);
    const middle = lo + (hi - lo) / 2;
    const state = evaluate(middle);
    if (!state) {
      unresolved.push([lo, hi]);
      return 'unresolved';
    }
    if (state.penetrating) {
      collision = collision ?? { degrees: middle, overlap: state.overlap };
      return 'collision';
    }
    const angularHalfWidth = Math.abs(hi - lo) * Math.PI / 360;
    const maximumDrift = state.radius * angularHalfWidth;
    // Strictly positive separating gap is essential. A touch allowed by
    // the epsilon in boxPenetration is not a proof of a clear interval.
    const gap = -state.overlap;
    if (gap > maximumDrift + eps) {
      certifiedIntervals++;
      return 'certified-clear';
    }
    if (depth === maxDepth) {
      unresolved.push([lo, hi]);
      return 'unresolved';
    }
    const left = interval(lo, middle, depth + 1);
    if (left === 'collision') return 'collision';
    const right = interval(middle, hi, depth + 1);
    if (right === 'collision') return 'collision';
    return left === 'certified-clear' && right === 'certified-clear'
      ? 'certified-clear' : 'unresolved';
  }
  try {
    const start = evaluate(startDeg);
    const end = evaluate(endDeg);
    if (!start || !end) throw new Error('endpoint probe budget exhausted');
    if (start.penetrating || end.penetrating) {
      const hit = start.penetrating ? start : end;
      collision = { degrees: hit.degrees, overlap: hit.overlap };
    }
    const status = collision ? 'collision' : interval(startDeg, endDeg, 0);
    return { status, collision, evaluatedAngles: probeCache.size,
      certifiedIntervals, unresolvedIntervals: unresolved,
      maxVisitedDepth, maxChecks, maxDepth, eps,
      method: 'rigid static-obstacle interval bound, not general continuous mesh collision' };
  } finally {
    joint.rotation.y = original;
    joint.updateWorldMatrix(true, true);
  }
}
