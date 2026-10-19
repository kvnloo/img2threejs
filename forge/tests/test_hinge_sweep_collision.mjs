/** Negative-control swept-fold regression. No WebGL or network needed. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { boxPenetration, readBox, sampleFold, certifyFoldSweep } from './hinge_sweep_collision.mjs';

function model() {
  const root = new THREE.Group();
  const pivot = new THREE.Group();
  pivot.position.set(0.5, 0, 0);
  root.add(pivot);
  const aligned = new THREE.Group();
  aligned.quaternion.setFromUnitVectors(
    new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1));
  pivot.add(aligned);
  const joint = new THREE.Group();
  aligned.add(joint);
  const counter = new THREE.Group();
  counter.quaternion.copy(aligned.quaternion).invert();
  joint.add(counter);
  const offset = new THREE.Group();
  offset.position.set(-0.5, 0, 0);
  counter.add(offset);

  const panel = new THREE.Mesh(new THREE.BoxGeometry(1, 0.04, 0.7));
  panel.position.set(1, 0, 0);
  offset.add(panel);
  const obstacle = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.24, 0.5));
  obstacle.position.set(0.5, 0.5, 0);
  root.add(obstacle);
  return { root, pivot, joint, panel, obstacle };
}
const sample = (start, end, step) =>
  Array.from({length: Math.round(Math.abs(end - start) / Math.abs(step)) + 1},
    (_, i) => start + Math.sign(end - start) * i * Math.abs(step));

test('SAT excludes touching, includes true penetration and preserves sign', () => {
  const a = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1));
  const b = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1));
  b.position.set(1, 0, 0);
  assert.equal(boxPenetration(a, b).penetrating, false);
  b.position.x = 0.98;
  assert.equal(boxPenetration(a, b).penetrating, true);
  assert.ok(boxPenetration(a, b).overlap > 0.019);
  b.position.x = 1.02;
  assert.equal(boxPenetration(a, b).penetrating, false);
});

test('rotated OBB detects diagonal separation that broad-phase AABBs cannot', () => {
  const a = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.12, 0.16));
  a.rotation.z = Math.PI / 4;
  const b = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.12, 0.16));
  b.rotation.z = Math.PI / 4;
  b.position.set(-0.3, 0.3, 0);
  // They are distinct parallel bars with perpendicular separation ~0.424.
  assert.equal(new THREE.Box3().setFromObject(a).intersectsBox(new THREE.Box3().setFromObject(b)), true);
  assert.equal(boxPenetration(a, b).penetrating, false);
});

test('signed fold catches intermediate collision hidden by both clear endpoints', () => {
  const { root, joint, panel, obstacle } = model();
  const angles = sample(0, 180, 5);
  const forward = sampleFold(joint, panel, obstacle, angles);
  assert.equal(forward.samples[0].penetrating, false, 'start pose must be clear');
  assert.equal(forward.samples.at(-1).penetrating, false, 'end pose must be clear');
  assert.ok(forward.firstCollision, 'mid-arc obstruction must be detected');
  assert.ok(forward.collisionSamples > 0, 'sweep cannot pass by checking endpoints only');
  assert.ok(forward.samples.some(s => s.degrees === 90 && s.penetrating));
  assert.equal(joint.rotation.y, 0, 'joint must be restored after sweep');
  root.updateMatrixWorld(true);
  assert.ok(readBox(panel).center.distanceTo(new THREE.Vector3(1, 0, 0)) < 1e-6);
});

test('same exact end pose via opposite-sign fold avoids obstruction', () => {
  const { joint, panel, obstacle } = model();
  const positive = sampleFold(joint, panel, obstacle, sample(0, 180, 5));
  const negative = sampleFold(joint, panel, obstacle, sample(0, -180, 5));
  assert.ok(positive.collisionSamples > 0);
  assert.equal(negative.collisionSamples, 0, 'wrong sign should be distinguishable by sweep');
  joint.rotation.y = Math.PI;
  const endPositive = readBox(panel).center;
  joint.rotation.y = -Math.PI;
  const endNegative = readBox(panel).center;
  assert.ok(endPositive.distanceTo(endNegative) < 1e-6, 'endpoints are identical');
});

test('non-box, malformed transforms and invalid sweeps fail closed', () => {
  const sphere = new THREE.Mesh(new THREE.SphereGeometry(1));
  const box = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1));
  assert.throws(() => boxPenetration(sphere, box), /BoxGeometry/);
  assert.throws(() => boxPenetration(box, box, -1), /epsilon/);
  const { joint, panel, obstacle } = model();
  assert.throws(() => sampleFold(joint, panel, obstacle, [0, NaN]), /nonfinite/);
  assert.equal(joint.rotation.y, 0);
});

test('adaptive check catches a 2.5-degree collision missed by the 5-degree samples', () => {
  const { joint, panel, obstacle } = model();
  panel.geometry.dispose();
  panel.geometry = new THREE.BoxGeometry(0.12, 0.008, 0.1);
  obstacle.geometry.dispose();
  obstacle.geometry = new THREE.BoxGeometry(0.012, 0.012, 0.12);
  const angle = THREE.MathUtils.degToRad(2.5);
  obstacle.position.set(0.5 + 0.5 * Math.cos(angle), 0.5 * Math.sin(angle), 0);
  const coarse = sampleFold(joint, panel, obstacle, [0, 5]);
  assert.equal(coarse.collisionSamples, 0, 'sparse endpoint samples should miss the collision');
  const verified = certifyFoldSweep(joint, panel, obstacle, 0, 5);
  assert.equal(verified.status, 'collision', JSON.stringify(verified));
  assert.equal(verified.collision.degrees, 2.5);
  assert.ok(verified.collision.overlap > 0);
  assert.equal(joint.rotation.y, 0, 'adaptive check must restore pose');
});

test('adaptive bound certifies a distant box without a dense sweep', () => {
  const { joint, panel, obstacle } = model();
  obstacle.position.set(12, 4, 0);
  const check = certifyFoldSweep(joint, panel, obstacle, 0, 180);
  assert.equal(check.status, 'certified-clear', JSON.stringify(check));
  assert.equal(check.unresolvedIntervals.length, 0);
  assert.ok(check.evaluatedAngles <= 20, 'far-field certificates should avoid dense sampling');
});

test('very long geometry along the hinge axis does not inflate angular radius', () => {
  const { joint, panel, obstacle } = model();
  panel.geometry.dispose();
  panel.geometry = new THREE.BoxGeometry(1, 0.04, 2000);
  obstacle.position.set(5, 0, 0);
  const verified = certifyFoldSweep(joint, panel, obstacle, 0, 180);
  assert.equal(verified.status, 'certified-clear', JSON.stringify(verified));
  assert.ok(verified.evaluatedAngles <= 3,
    'axis-aligned extent cannot require thousands of useless samples');
});

test('uniformly scaled parents keep the conservative separation guarantee', () => {
  const { root, joint, panel, obstacle } = model();
  root.scale.setScalar(2.5);
  obstacle.position.set(10, 2, 0);
  const verified = certifyFoldSweep(joint, panel, obstacle, -90, 180);
  assert.equal(verified.status, 'certified-clear', JSON.stringify(verified));
});

test('positive sweep detects obstacle; negative sweep is bounded-clear', () => {
  const { joint, panel, obstacle } = model();
  const positive = certifyFoldSweep(joint, panel, obstacle, 0, 180);
  const negative = certifyFoldSweep(joint, panel, obstacle, 0, -180);
  assert.equal(positive.status, 'collision', JSON.stringify(positive));
  assert.equal(negative.status, 'certified-clear', JSON.stringify(negative));
  assert.equal(joint.rotation.y, 0);
});

test('insufficient angular resolution is unresolved, not a false safety verdict', () => {
  const { joint, panel, obstacle } = model();
  panel.geometry.dispose();
  panel.geometry = new THREE.BoxGeometry(0.12, 0.008, 0.1);
  obstacle.geometry.dispose();
  obstacle.geometry = new THREE.BoxGeometry(0.012, 0.012, 0.12);
  obstacle.position.set(1.085, 0, 0);
  const shallow = certifyFoldSweep(joint, panel, obstacle, 0, 5, { maxDepth: 0 });
  assert.equal(shallow.status, 'unresolved', JSON.stringify(shallow));
  assert.equal(shallow.unresolvedIntervals.length, 1);
  assert.equal(joint.rotation.y, 0);
});

test('adaptive check refuses moving obstacle, nonuniform parent and invalid budget', () => {
  const { root, joint, panel, obstacle } = model();
  assert.throws(() => certifyFoldSweep(joint, panel, obstacle, 0, 90,
    { maxChecks: 2 }), /budget/);
  assert.throws(() => certifyFoldSweep(joint, panel, obstacle, 0, 90,
    { maxDepth: -1 }), /depth/);
  assert.throws(() => certifyFoldSweep(joint, panel, obstacle, NaN, 90), /finite/);
  joint.add(obstacle);
  assert.throws(() => certifyFoldSweep(joint, panel, obstacle, 0, 90), /subtree/);
  root.add(obstacle);
  root.scale.set(2, 1, 1);
  assert.throws(() => certifyFoldSweep(joint, panel, obstacle, 0, 90), /uniform scale/);
  root.scale.set(1, 1, 1);
  assert.equal(joint.rotation.y, 0);
});

if (process.env.HINGE_SWEEP_OUTPUT) {
  const { writeFileSync } = await import('node:fs');
  const { joint, panel, obstacle } = model();
  const forward = sampleFold(joint, panel, obstacle, sample(0, 180, 5));
  const reverse = sampleFold(joint, panel, obstacle, sample(0, -180, 5));
  const forwardAdaptive = certifyFoldSweep(joint, panel, obstacle, 0, 180);
  const reverseAdaptive = certifyFoldSweep(joint, panel, obstacle, 0, -180);
  const payload = {
    test: 'sweep OBB SAT, test-only negative control',
    sampleSpacingDegrees: 5,
    clearEndPoses: !forward.samples[0].penetrating && !forward.samples.at(-1).penetrating,
    positiveCollisionSamples: forward.collisionSamples,
    negativeCollisionSamples: reverse.collisionSamples,
    firstCollision: forward.firstCollision,
    adaptivePositive: forwardAdaptive,
    adaptiveNegative: reverseAdaptive,
    limitations: ['5-degree samples may miss impacts; adaptive result uses conservative displacement-bound certificates',
      'rigid stationary obstacles and non-sheared boxes only', 'crafted obstacle, not real cardboard physics'],
  };
  writeFileSync(process.env.HINGE_SWEEP_OUTPUT, JSON.stringify(payload, null, 2) + '\n');
  console.log('HINGE_SWEEP_NEGATIVE_CONTROL:', JSON.stringify(payload));
}
