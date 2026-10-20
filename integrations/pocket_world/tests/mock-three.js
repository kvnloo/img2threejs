(() => {
class Vec3 {
  constructor(x=0,y=0,z=0) { this.x=x; this.y=y; this.z=z; }
  set(x,y,z) { this.x=x; this.y=y; this.z=z; return this; }
  copy(v) { return this.set(v.x, v.y, v.z); }
  lerpVectors(a,b,t) { return this.set(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t,a.z+(b.z-a.z)*t); }
}
class Color { constructor(hex=0){this.hex=hex;} setHex(hex){this.hex=hex;return this;} copy(v){this.hex=v.hex;return this;} }
class Node {
  constructor(){ this.position=new Vec3();this.scale=new Vec3(1,1,1);this.rotation={x:0,y:0,z:0};this.visible=true;this.children=[];this.userData={}; }
  add(...nodes){this.children.push(...nodes);}
  remove(node){this.children=this.children.filter(n=>n!==node);}
  updateMatrix(){this.matrix={position:{...this.position},scale:{...this.scale}};}
}
class Group extends Node {}
class Scene extends Node {}
class Object3D extends Node {}
class Camera extends Node { updateProjectionMatrix(){} }
class Mesh extends Node {constructor(geometry,material){super();this.geometry=geometry;this.material=material;} }
class InstancedMesh extends Mesh {
  constructor(geometry,material,count){super(geometry,material);this.count=count;this.instanceColor={};this.instanceMatrix={};this.matrices=[];this.colors=[];}
  setColorAt(i,color){this.colors[i]=color.hex;}
  setMatrixAt(i,matrix){this.matrices[i]=matrix;}
  computeBoundingSphere(){}
  dispose(){this.disposed=true;}
}
class Geometry {constructor(...args){this.args=args;}dispose(){this.disposed=true;} setAttribute(name,attr){this[name]=attr;} }
class Material {constructor(opts){this.options=opts;}dispose(){this.disposed=true;} }
class Light extends Node {constructor(a,b){super();this.color=a;this.intensity=b;} }
class FogExp2 {constructor(color,density){this.color=new Color(color);this.density=density;} }
class Points extends Mesh {}
class Renderer {
  constructor({canvas}){this.domElement=canvas;}
  setPixelRatio(ratio){window.__mockRenderDpr=ratio;}
  setSize(width,height){window.__mockRenderSize={width,height};}
  render(){window._frameCount=(window._frameCount||0)+1;}
}
class Raycaster {
  setFromCamera(){}
  intersectObjects(nodes){
    if(window.__pickBeaconObjects){
      return window.__pickBeaconObjects.filter(object=>nodes.includes(object)).map(object=>({object}));
    }
    const object=nodes[window.__pickBeacon];
    return object?[{object}]:[];
  }
  intersectObject(){return window.__pickTile!==undefined?[{instanceId:window.__pickTile}]:[]}
}
class OrbitControls {
  constructor(){this.target=new Vec3();this.autoRotate=false;}
  update(){}
}
const geometryNames=['BoxGeometry','EdgesGeometry','IcosahedronGeometry','TorusGeometry','BufferGeometry'];
const materialNames=['MeshStandardMaterial','MeshBasicMaterial','LineBasicMaterial','PointsMaterial'];
const classes=Object.fromEntries(geometryNames.map(n=>[n,Geometry]));
Object.assign(classes,Object.fromEntries(materialNames.map(n=>[n,Material])));
window.__THREE={...classes, WebGLRenderer:Renderer, Scene, Group, Mesh, InstancedMesh,Object3D,PerspectiveCamera:Camera, DirectionalLight:Light,HemisphereLight:Light,Points,LineSegments:Mesh, FogExp2,BufferAttribute:Geometry,Raycaster,Vector2:class{set(x,y){this.x=x;this.y=y;}},Vector3:Vec3,Color,
  SRGBColorSpace:0, ACESFilmicToneMapping:1};
window.__OrbitControls=OrbitControls;
})();
