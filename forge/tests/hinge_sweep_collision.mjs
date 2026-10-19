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
