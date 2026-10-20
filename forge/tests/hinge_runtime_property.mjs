/** Independent position/orientation oracle for the actual generated Three.js factory.
 * Do not use the hinge scene's own pivot subgroups as the expected transform:
 * that would confirm the same implementation twice.
 */
export function checkGeneratedHingeProperties(root, runtime, THREE) {
  const cfg = {
    lid:{parent:'base',start:[0.75,0,0],end:[0.75,0,1]},
    flap:{parent:'lid',start:[0.75,0,0],end:[0.75,0,1]},
    diagonal:{parent:'base',start:[0.2,-0.7,-0.2],end:[1.2,0.3,0.8]},
    reverse:{parent:'base',start:[-0.4,0.15,-0.1],end:[-0.4,-0.85,-0.1]},
    'diag-child':{parent:'diagonal',start:[0,0.1,0],end:[-0.25,0.6,0.3]},
  };
  const entries=Object.entries(cfg);
  const vector=xyz=>new THREE.Vector3(...xyz);
  const approx=(a,b,label,tolerance=2e-5)=>{
    if (a.distanceTo(b)>tolerance) {
      throw new Error(label+': '+a.toArray()+' expected '+b.toArray());
    }
  };
  const oldAngles=Object.fromEntries(entries.map(([id])=>[id,runtime.hinges[id]?.rotation.y]));
  const oldRotations=Object.fromEntries(entries.map(([id])=>[id,runtime.nodes[id].rotation.clone()]));
  const oldScale=runtime.nodes.base.scale.clone();
  const positions=Object.fromEntries(entries.map(([id])=>[id,runtime.nodes[id].position.clone()]));
  if (Math.abs(oldAngles.reverse-THREE.MathUtils.degToRad(-37))>1e-11 ||
      Math.abs(oldAngles['diag-child']-THREE.MathUtils.degToRad(27))>1e-11) {
    throw new Error('generated runtime lost nonzero signed hinge rest angles');
  }
  let seed=0x118a517;
  const rand=()=>{
    seed=(Math.imul(seed,1664525)+1013904223)>>>0;
    return seed/4294967296;
  };
  const frames=[[1,1,1],[1.2,0.9,1.4],[-1.1,1.35,0.8]];
  let points=0,axes=0,cases=0;
  try {
    for (const frame of frames) {
      runtime.nodes.base.scale.set(...frame);
      for (let caseIndex=0;caseIndex<64;caseIndex++) {
        for (const [id] of entries) {
          runtime.hinges[id].rotation.y=(rand()*2-1)*Math.PI;
          runtime.nodes[id].rotation.set(
            (rand()-0.5)*0.8,(rand()-0.5)*0.8,(rand()-0.5)*0.8);
        }
        root.updateMatrixWorld(true);
        for (const [id,item] of entries) {
          const node=runtime.nodes[id],parent=runtime.nodes[item.parent];
          const origin=vector(item.start),axis=vector(item.end).sub(origin).normalize();
          for(const xyz of [[0,0,0],[0.31,-0.23,0.47],[-0.13,0.19,0.06]]) {
            const point=vector(xyz);
            const parentLocal=point.clone().multiply(node.scale)
              .applyQuaternion(node.quaternion).add(node.position);
            const expected=parent.localToWorld(parentLocal.sub(origin)
              .applyAxisAngle(axis,runtime.hinges[id].rotation.y).add(origin));
            const actual=node.localToWorld(point);
            approx(actual,expected,'world '+id+' frame='+frame+' case='+caseIndex);
            points++;
          }
          const nodeLocalAxis=origin.clone().sub(node.position)
            .applyQuaternion(node.quaternion.clone().invert()).divide(node.scale);
          approx(node.localToWorld(nodeLocalAxis),parent.localToWorld(origin.clone()),
            'axis invariant '+id);
          approx(node.position,positions[id],'authored node position '+id,2e-8);
          axes++;
        }
        cases++;
      }
    }
  } finally {
    runtime.nodes.base.scale.copy(oldScale);
    for(const [id] of entries) {
      runtime.hinges[id].rotation.y=oldAngles[id];
      runtime.nodes[id].rotation.copy(oldRotations[id]);
    }
    root.updateMatrixWorld(true);
  }
  return {seed:'0x118a517',cases, joints:entries.length,
    pointAssertions:points,axisAssertions:axes,
    frames:frames.map(f=>f.join(',')),antiParallelAxis:true,
    nonzeroRest:true,nested:true,reflectedParent:true};
}
