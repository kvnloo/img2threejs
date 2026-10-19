#!/usr/bin/env node
/** Real Three.js top-view pixels -> measured reference -> browser mesh exporter -> plan-taper gate.
 * A self-contained synthetic form regression, NOT Ferrari or real-photograph evidence.
 * Install optional browser dependencies outside core and pin the exporter checkout in CI.
 */
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {createServer} from 'node:http';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {pathToFileURL, fileURLToPath} from 'node:url';
import {
  STATIONS, REFERENCE_PROFILE, STADIUM_PROFILE, VIEW,
  MODEL_X_SCALE, MODEL_X_OFFSET, referencePixelColumn, referenceTableFromColumns,
} from './vehicle_reference_pixels.mjs';

const repoRoot = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const depsRoot = process.env.IMG2THREEJS_SHOWCASE_ROOT;
const exporterFile = process.env.IMG2_EXPORTER_PATH;
assert.ok(depsRoot, 'set IMG2THREEJS_SHOWCASE_ROOT to isolated Playwright + Three.js installation');
assert.ok(exporterFile, 'set IMG2_EXPORTER_PATH to the pinned PR #35 exporter script');
const {chromium} = createRequire(join(resolve(depsRoot), 'package.json'))('playwright');
const {runCli} = await import(pathToFileURL(resolve(exporterFile)).href);
const threeModule = join(resolve(depsRoot), 'node_modules', 'three', 'build', 'three.module.js');
const output = resolve(process.env.VEHICLE_AB_OUTPUT || join(process.env.RUNNER_TEMP || tmpdir(), 'vehicle-plan-ab'));
await mkdir(output, {recursive: true});

function preview(mode) {
  const profile = mode === 'stadium' ? STADIUM_PROFILE : REFERENCE_PROFILE;
  const partial = mode === 'partial';
  return `<!doctype html><html><head><meta charset="utf-8"><title>Vehicle plan-taper test</title>
  <style>html,body{background:#122031;margin:0;width:100%;height:100%;overflow:hidden}</style></head><body>
  <script type="module">
  import * as THREE from '/three/three.module.js';
  const stations = ${JSON.stringify(STATIONS.map(s => s.localX))};
  const widths = ${JSON.stringify(profile)};
  const verts = [], idx = [];
  for (let i = 0; i < stations.length; i++) {
    const x = stations[i], w = widths[i] / 2;
    for (const [y, z] of [[0,-w],[0,w],[.45,w],[.45,-w]]) verts.push(x,y,z);
  }
  for (let i = 0; i < stations.length-1; i++) {
    const a = i*4, b = (i+1)*4;
    for (let k = 0; k < 4; k++) {
      const next = (k+1)%4;
      idx.push(a+k,b+k,b+next, a+k,b+next,a+next);
    }
  }
  idx.push(0,1,2,0,2,3);
  const last = (stations.length-1)*4;
  idx.push(last,last+2,last+1,last,last+3,last+2);
  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.Float32BufferAttribute(verts,3));
  geom.setIndex(idx);
  geom.computeVertexNormals();
  if (${JSON.stringify(partial)}) geom.setDrawRange(0,idx.length-3);
  const body = new THREE.Mesh(geom,new THREE.MeshBasicMaterial({color:0x28dd81,side:THREE.DoubleSide}));
  body.name = 'vehicle-body';
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x122031);
  const modelRoot = new THREE.Group();
  scene.add(modelRoot);
  const shifted = new THREE.Group();
  shifted.position.set(${MODEL_X_OFFSET},.2,0);
  shifted.scale.set(${MODEL_X_SCALE},1,1.4);
  shifted.add(body);
  modelRoot.add(shifted);
  // Roof and wheels give this a recognisable 3D vehicle assembly. The green
  // body edges remain visible, so we can measure the width from actual pixels.
  const cabin = new THREE.Mesh(new THREE.BoxGeometry(1.35,.27,.6),
    new THREE.MeshBasicMaterial({color:0x273a58}));
  cabin.name = 'greenhouse';
  cabin.position.set(0,.62,0);
  shifted.add(cabin);
  for (const x of [-1.18,1.18]) for (const z of [-.58,.58]) {
    const wheel = new THREE.Mesh(new THREE.CylinderGeometry(.29,.29,.17,18),
      new THREE.MeshBasicMaterial({color:0x17212b}));
    wheel.name = 'wheel-'+x+'-'+z;
    wheel.rotation.x=Math.PI/2;
    wheel.position.set(x,.04,z);
    shifted.add(wheel);
  }
  const studio = new THREE.Mesh(new THREE.PlaneGeometry(15,15),
    new THREE.MeshBasicMaterial({color:0x203348}));
  studio.rotation.x=-Math.PI/2;
  studio.position.y=-.12;
  studio.name='studio-ground';
  scene.add(studio); // Deliberately outside the model root.
  const renderer=new THREE.WebGLRenderer({antialias:false,preserveDrawingBuffer:true});
  renderer.setPixelRatio(1);
  renderer.setSize(${VIEW.width},${VIEW.height});
  document.body.appendChild(renderer.domElement);
  const camera=new THREE.OrthographicCamera(${VIEW.left},${VIEW.right},${VIEW.top},${VIEW.bottom},.1,100);
  camera.position.set(0,9,0);
  camera.up.set(0,0,-1);
  camera.lookAt(0,0,0);
  renderer.render(scene,camera);
  window.__IMG2THREEJS_VIEWER__={scene,modelRoot,started:true};
  window.__IMG2THREEJS_MESH_ROOT__=modelRoot;
  window.__IMG2THREEJS_RENDERED__=!!renderer.getContext();
  window.__IMG2THREEJS_READY__=true;
  </script></body></html>`;
}

const server = createServer(async(req,res) => {
  const pathname = new URL(req.url || '/', 'http://127.0.0.1').pathname;
  try {
    if (['/reference','/matching','/stadium','/partial'].includes(pathname)) {
      res.writeHead(200, {'content-type':'text/html; charset=utf-8'});
      res.end(preview(pathname.slice(1)));
    } else if(pathname === '/three/three.module.js') {
      res.writeHead(200, {'content-type':'text/javascript; charset=utf-8'});
      res.end(await readFile(threeModule));
    } else {
      res.writeHead(404); res.end('Not found');
    }
  } catch(error) {
    res.writeHead(500);res.end(String(error));
  }
});
await new Promise((ok, fail) => {
  server.once('error',fail);
  server.listen(0,'127.0.0.1',ok);
});
const origin=`http://127.0.0.1:${server.address().port}`;

async function capture(page, mode, filename) {
  const errors=[];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(origin+'/'+mode,{waitUntil:'domcontentloaded'});
  await page.waitForFunction('window.__IMG2THREEJS_READY__ === true && window.__IMG2THREEJS_RENDERED__ === true');
  assert.deepEqual(errors,[],`browser error in ${mode}`);
  const screenshot=join(output,filename);
  await page.locator('canvas').screenshot({path:screenshot});
  return screenshot;
}

function gate(geometry, sections) {
  return spawnSync('python3', [
    'integrations/vehicle_form/plan_taper.py','--geometry',geometry,
    '--sections',sections,'--mesh','vehicle-body','--json',
  ], {cwd:repoRoot,encoding:'utf8',maxBuffer:2_000_000});
}

const browser=await chromium.launch({headless:true});
try {
  const page=await browser.newPage({viewport:{width:VIEW.width,height:VIEW.height},deviceScaleFactor:1});
  const sourceImage=await capture(page,'reference','reference-top.png');
  const columns=STATIONS.map((_,i)=>referencePixelColumn(i));
  // Return only five RGBA columns (not a multi-megabyte framebuffer) to Node.
  const pixelColumns=await page.evaluate((xs)=>{
    const canvas=document.querySelector('canvas');
    const mirror=document.createElement('canvas');
    mirror.width=canvas.width;mirror.height=canvas.height;
    const ctx=mirror.getContext('2d',{willReadFrequently:true});
    ctx.drawImage(canvas,0,0);
    return xs.map(x=>Array.from(ctx.getImageData(x,0,1,canvas.height).data));
  },columns);
  const sourceHash=createHash('sha256').update(await readFile(sourceImage)).digest('hex');
  const table=referenceTableFromColumns(pixelColumns,
    `synthetic Three.js orthographic rendered reference: reference-top.png sha256=${sourceHash}`);
  // The value of this check is that the measured table is derived from actual
  // rendered pixels. A hard-coded expected 3D station width cannot certify it.
  assert.ok(table.stations.every(s=>s.referenceBodyPixelCount>=12),
    'WebGL reference has too few vehicle-colored pixels to serve as evidence');
  const sectionPath=join(output,'pixel-measured-sections.json');
  await writeFile(sectionPath,JSON.stringify(table,null,2)+'\n');

  const matchingImage=await capture(page,'matching','matching-top.png');
  const stadiumImage=await capture(page,'stadium','stadium-top.png');
  const matchingGeometry=join(output,'matching-meshes.json');
  const stadiumGeometry=join(output,'stadium-meshes.json');
  assert.equal(await runCli(['--url',origin+'/matching','--out',matchingGeometry,
    '--ready-flag','__IMG2THREEJS_READY__']),0);
  assert.equal(await runCli(['--url',origin+'/stadium','--out',stadiumGeometry,
    '--ready-flag','__IMG2THREEJS_READY__']),0);
  const evidence=JSON.parse(await readFile(matchingGeometry,'utf8'));
  assert.equal(evidence.incomplete,false);
  assert.equal(evidence.coordinateSpace,'world');
  assert.notEqual(evidence.rootSource,'scene-explicit');
  assert.deepEqual(evidence.meshes.filter(m=>m.name==='vehicle-body').map(m=>m.name),['vehicle-body']);
  assert.equal(evidence.meshes.some(m=>m.name==='studio-ground'),false);
  assert.ok(evidence.meshes.length>=2,'expected body plus wheels/greenhouse');
  const match=gate(matchingGeometry,sectionPath);
  const flat=gate(stadiumGeometry,sectionPath);
  await writeFile(join(output,'matching-gate.json'),match.stdout||'{}');
  await writeFile(join(output,'stadium-gate.json'),flat.stdout||'{}');
  assert.equal(match.status,0,`matching shape should pass: ${match.stderr} ${match.stdout}`);
  assert.equal(flat.status,1,`stadium shape must fail: ${flat.stderr} ${flat.stdout}`);
  const matchedReport=JSON.parse(match.stdout),flatReport=JSON.parse(flat.stdout);
  assert.equal(matchedReport.passed,true);
  assert.equal(flatReport.passed,false);
  assert.ok(flatReport.failures.some(f=>/taper|station/.test(f)), 'missing plan-form regression diagnostic');

  // An incomplete exporter must leave no successful evidence and must not pass
  // the downstream geometry gate if someone explicitly feeds its diagnostic.
  const stale=join(output,'partial-meshes.json');
  await writeFile(stale,JSON.stringify(evidence));
  assert.equal(await runCli(['--url',origin+'/partial','--out',stale]),2);
  const fs=await import('node:fs');
  assert.equal(fs.existsSync(stale),false,'partial retry preserved stale successful geometry');
  const incomplete=stale+'.incomplete.json';
  const partialReport=JSON.parse(await readFile(incomplete,'utf8'));
  assert.equal(partialReport.incomplete,true);
  assert.equal(gate(incomplete,sectionPath).status,2);

  const images=await Promise.all([sourceImage,matchingImage,stadiumImage].map(p=>readFile(p)));
  const cards=['Synthetic reference pixels','Matched reconstruction · PASS','Constant-width body · FAIL'];
  const collage=await browser.newPage({viewport:{width:1230,height:565},deviceScaleFactor:1});
  await collage.setContent(`<!doctype html><html><head><style>
    body{background:#09131d;color:#eaf5ef;font:16px system-ui;margin:0;padding:25px}
    h1{font-size:24px;margin:0 0 8px}p{font-size:13px;color:#9cb2c4;margin:0 0 20px}
    main{display:flex;gap:15px}.card{width:380px}.card h2{font-size:15px;margin:0 0 8px}
    img{width:380px;height:190px;object-fit:cover;border-radius:7px;border:1px solid #314759}
    .note{font-size:12px;color:#9cb2c4;margin-top:14px}
  </style></head><body><h1>Vehicle plan-taper | Browser A/B evidence</h1>
  <p>Reference station widths measured from actual Chromium / Three.js top-view pixels. Geometry widths measured by triangle-plane intersections.</p>
  <main>${images.map((b,i)=>`<section class="card"><h2>${cards[i]}</h2><img src="data:image/png;base64,${b.toString('base64')}"></section>`).join('')}</main>
  <div class="note">Synthetic regression only · No Ferrari photo or independent real-world dimensional accuracy claimed</div></body></html>`);
  await collage.screenshot({path:join(output,'vehicle-ab-comparison.png')});
  await collage.close();
  console.log(JSON.stringify({result:'pass',matching:matchedReport.passed,stadiumRejected:!flatReport.passed,
    measuredPixels:table.stations.map(s=>({id:s.id,pixels:s.referenceBodyPixelCount,width:s.referenceWidth})),
    maxMatchingWidthError:Math.max(...matchedReport.stations.map(s=>s.normalizedWidthError)),
    rejectedFailures:flatReport.failures,output,referenceImageHash:sourceHash},null,2));
  await page.close();
} finally {
  await browser.close();
  await new Promise(done=>server.close(done));
}
