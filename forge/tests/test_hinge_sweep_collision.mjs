/** Negative-control swept-fold regression. No WebGL or network needed. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { boxPenetration, readBox, sampleFold } from './hinge_sweep_collision.mjs';

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

if (process.env.HINGE_SWEEP_OUTPUT) {
  const { writeFileSync } = await import('node:fs');
  const { joint, panel, obstacle } = model();
  const forward = sampleFold(joint, panel, obstacle, sample(0, 180, 5));
  const reverse = sampleFold(joint, panel, obstacle, sample(0, -180, 5));
  const payload = {
    test: 'sweep OBB SAT, test-only negative control',
    sampleSpacingDegrees: 5,
    clearEndPoses: !forward.samples[0].penetrating && !forward.samples.at(-1).penetrating,
    positiveCollisionSamples: forward.collisionSamples,
    negativeCollisionSamples: reverse.collisionSamples,
    firstCollision: forward.firstCollision,
    limitations: ['sampled in time; possible missed between-step impacts',
      'rigid box volumes only', 'crafted obstacle, not a claim about real cardboard physics'],
  };
  writeFileSync(process.env.HINGE_SWEEP_OUTPUT, JSON.stringify(payload, null, 2) + '\n');
  console.log('HINGE_SWEEP_NEGATIVE_CONTROL:', JSON.stringify(payload));
}
