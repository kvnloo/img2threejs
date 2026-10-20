import * as THREE from 'three';
import { createFoldingCartonModel } from './factory.ts';
import { checkGeneratedHingeProperties } from './hinge_runtime_property.mjs';

const root = createFoldingCartonModel();
const runtime = root.userData.sculptRuntime;
const scene = new THREE.Scene();
scene.background = new THREE.Color('#eef2f8');
scene.add(root);
scene.add(new THREE.HemisphereLight(0xffffff, 0x8190b3, 2.4));
const sun = new THREE.DirectionalLight(0xffffff, 2.5);
sun.position.set(3, 5, 6);
scene.add(sun);
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(740, 540);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.append(renderer.domElement);
const camera = new THREE.PerspectiveCamera(38, 740 / 540, 0.1, 100);
camera.position.set(4, 3.1, 6);
camera.lookAt(0.7, 0.5, 0);
const pos = (id) => runtime.nodes[id].getWorldPosition(new THREE.Vector3());
const near = (p, q, label, tolerance = 1e-5) => {
  if (p.distanceTo(q) > tolerance) throw new Error(label + ': ' + p.toArray() + ' != ' + q.toArray());
};
const rotate = (point, origin, axis, radians) =>
  point.clone().sub(origin).applyAxisAngle(axis, radians).add(origin);
const zAxis = new THREE.Vector3(0, 0, 1);
const lidHinge = new THREE.Vector3(0.75, 0, 0);
function checkSeams(label) {
  near(runtime.nodes.base.localToWorld(new THREE.Vector3(0.75, 0, 0)),
    runtime.nodes.lid.localToWorld(new THREE.Vector3(-0.75, 0, 0)), label + ' lid crease');
  near(runtime.nodes.lid.localToWorld(new THREE.Vector3(0.75, 0, 0)),
    runtime.nodes.flap.localToWorld(new THREE.Vector3(-0.25, 0, 0)), label + ' flap crease');
}

function testTransforms() {
  root.updateMatrixWorld(true);
  if (!runtime.hinges.lid || !runtime.hinges.flap || !runtime.hinges.diagonal) {
    throw new Error('hinge runtime keys missing');
  }
  near(runtime.nodes.lid.position, new THREE.Vector3(1.5, 0, 0), 'node local transform changed');
  near(pos('lid'), new THREE.Vector3(1.5, 0, 0), 'zero-angle lid position');
  near(pos('flap'), new THREE.Vector3(2.5, 0, 0), 'zero-angle flap position');
  checkSeams('rest');

  const lid0 = pos('lid').clone();
  const flap0 = pos('flap').clone();
  runtime.hinges.lid.rotation.y = Math.PI / 2;
  root.updateMatrixWorld(true);
  near(pos('lid'), rotate(lid0, lidHinge, zAxis, Math.PI / 2), 'lid around edge');
  near(pos('flap'), rotate(flap0, lidHinge, zAxis, Math.PI / 2), 'nested flap follows lid');

  checkSeams('90-degree lid');
  const parentAnchor = runtime.nodes.lid.localToWorld(new THREE.Vector3(0.75, 0, 0));
  const beforeFlap = pos('flap').clone();
  runtime.hinges.flap.rotation.y = -Math.PI / 4;
  root.updateMatrixWorld(true);
  near(pos('flap'), rotate(beforeFlap, parentAnchor, zAxis, -Math.PI / 4), 'flap about edge');
  near(runtime.nodes.lid.position, new THREE.Vector3(1.5, 0, 0), 'lid node pose mutated by hinge');
  checkSeams('45-degree flap');

  const diagStart = new THREE.Vector3(0.2, -0.7, -0.2);
  const diagAxis = new THREE.Vector3(1, 1, 1).normalize();
  const diagonal0 = pos('diagonal').clone();
  runtime.hinges.diagonal.rotation.y = Math.PI / 3;
  root.updateMatrixWorld(true);
  near(pos('diagonal'), rotate(diagonal0, diagStart, diagAxis, Math.PI / 3), 'diagonal arbitrary axis');

  runtime.hinges.flap.rotation.y = 0;
  runtime.hinges.lid.rotation.y = 0;
  runtime.hinges.diagonal.rotation.y = 0;
  root.updateMatrixWorld(true);
  near(pos('lid'), lid0, 'lid did not return to rest');
  near(pos('flap'), flap0, 'flap did not return to rest');
  near(pos('diagonal'), diagonal0, 'diagonal did not return to rest');
  for (let degrees = 0; degrees <= 90; degrees += 5) {
    runtime.hinges.lid.rotation.y = THREE.MathUtils.degToRad(degrees);
    runtime.hinges.flap.rotation.y = THREE.MathUtils.degToRad(-degrees / 2);
    root.updateMatrixWorld(true);
    checkSeams('sweep ' + degrees);
    if (!pos('lid').toArray().every(Number.isFinite)) throw new Error('nonfinite swept hinge pose');
  }
  return { nodes: Object.keys(runtime.nodes).length, hinges: Object.keys(runtime.hinges).length };
}

window.__hingeSmoke = {
  testTransforms,
  testPropertySweeps() {
    return checkGeneratedHingeProperties(root, runtime, THREE);
  },
  render(degrees) {
    runtime.meshes.diagonal.visible = false;
    runtime.hinges.lid.rotation.y = THREE.MathUtils.degToRad(degrees);
    runtime.hinges.flap.rotation.y = THREE.MathUtils.degToRad(-degrees / 2);
    root.updateMatrixWorld(true);
    renderer.render(scene, camera);
    if (renderer.info.render.calls < 1) throw new Error('nothing drawn');
    return { drawCalls: renderer.info.render.calls, triangles: renderer.info.render.triangles };
  },
};
window.__hingeReady = true;
