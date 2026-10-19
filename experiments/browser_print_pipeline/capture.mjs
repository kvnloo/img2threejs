#!/usr/bin/env node
/** Real Chromium/WebGL -> model-root mesh receipts for STL/OBJ verification. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { readFile, mkdir, access } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const deps = process.env.IMG2THREEJS_SHOWCASE_ROOT;
const exporter = process.env.IMG2THREEJS_EXPORTER_PATH;
const destination = process.env.IMG2THREEJS_PRINT_EVIDENCE_DIR;
assert.ok(deps && exporter && destination, 'missing isolated browser, exporter or evidence path');
const { runCli } = await import(pathToFileURL(resolve(exporter)).href);
const { chromium } = createRequire(join(resolve(deps), 'package.json'))('playwright');
const three = join(resolve(deps), 'node_modules', 'three', 'build', 'three.module.js');
const out = resolve(destination);
await mkdir(out, { recursive: true });

function html(mode) {
  return '<!doctype html><meta charset="utf-8"><body style="margin:0;background:#101820">' +
  '<script type="module">import * as THREE from "/three.module.js";' +
  'const mode = ' + JSON.stringify(mode) + ';' +
  'const scene=new THREE.Scene(); scene.background=new THREE.Color(0x101820);' +
  'const root=new THREE.Group(); scene.add(root);' +
  'if(mode==="instances"){' +
  'const mesh=new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshBasicMaterial({color:0xffffff}),2);' +
  'mesh.name="copies";mesh.setMatrixAt(0,new THREE.Matrix4().makeTranslation(0,0,0));' +
  'mesh.setMatrixAt(1,new THREE.Matrix4().makeTranslation(4,0,0));' +
  'mesh.setColorAt(0,new THREE.Color(0xffaa55));mesh.setColorAt(1,new THREE.Color(0x55aaff));root.add(mesh);' +
  '}else{' +
  'const geom=new THREE.BoxGeometry(1,1,1);if(mode==="partial")geom.setDrawRange(0,18);' +
  'const mesh=new THREE.Mesh(geom,new THREE.MeshBasicMaterial({color:0x55dd99}));' +
  'mesh.name="subject-box";mesh.position.set(2,1,0);mesh.scale.set(2,1,1);root.add(mesh);}' +
  'const floor=new THREE.Mesh(new THREE.PlaneGeometry(15,15),new THREE.MeshBasicMaterial({color:0x992222}));' +
  'floor.name="studio-ground";floor.rotation.x=-Math.PI/2;floor.position.y=-1.2;scene.add(floor);' +
  'const renderer=new THREE.WebGLRenderer({antialias:false,preserveDrawingBuffer:true});renderer.setSize(512,384);' +
  'document.body.appendChild(renderer.domElement);' +
  'const camera=new THREE.PerspectiveCamera(50,512/384,0.1,100);' +
  'camera.position.set(8,5,9);camera.lookAt(1.5,0.3,0);renderer.render(scene,camera);' +
  'const buffer=document.createElement("canvas");buffer.width=512;buffer.height=384;' +
  'const ctx=buffer.getContext("2d",{willReadFrequently:true});ctx.drawImage(renderer.domElement,0,0);' +
  'const bytes=ctx.getImageData(0,0,512,384).data;let visible=0;' +
  'for(let i=0;i<bytes.length;i+=4)if(Math.abs(bytes[i]-16)+Math.abs(bytes[i+1]-24)+Math.abs(bytes[i+2]-32)>110)visible++;' +
  'window.__RENDER_EVIDENCE__={webgl:Boolean(renderer.getContext()),visible};' +
  'window.__IMG2THREEJS_VIEWER__={scene,explodeRoot:root,started:true};' +
  'window.__IMG2THREEJS_READY__=true;</script></body>';
}

const server = createServer(async(req,res)=>{
  try {
    const name=new URL(req.url,'http://localhost').pathname.slice(1);
    if(name==='three.module.js'){
      res.writeHead(200,{'content-type':'text/javascript'});
      res.end(await readFile(three));
    }else if(['box','instances','partial'].includes(name)){
      res.writeHead(200,{'content-type':'text/html'});
      res.end(html(name));
    }else {res.writeHead(404);res.end('Not found');}
  }catch(error){res.writeHead(500);res.end(String(error));}
});
await new Promise((ok,fail)=>{
  server.once('error',fail);server.listen(0,'127.0.0.1',ok);
});
const url='http://127.0.0.1:'+server.address().port+'/';
try {
  const browser=await chromium.launch({headless:true,args:['--enable-webgl','--use-gl=angle','--use-angle=swiftshader']});
  try {
    for(const mode of ['box','instances']){
      const page=await browser.newPage({viewport:{width:512,height:384},deviceScaleFactor:1});
      const errors=[];page.on('pageerror',e=>errors.push(String(e)));
      await page.goto(url+mode);
      await page.waitForFunction(()=>window.__IMG2THREEJS_READY__===true);
      const state=await page.evaluate(()=>window.__RENDER_EVIDENCE__);
      assert.equal(state.webgl,true);
      assert.ok(state.visible>1500,'blank framebuffer');
      assert.deepEqual(errors,[]);
      await page.locator('canvas').screenshot({path:join(out,mode+'.png')});
      await page.close();
      const filename=join(out,mode+'.json');
      assert.equal(await runCli(['--url',url+mode,'--out',filename,
        '--ready-flag','__IMG2THREEJS_READY__']),0);
      const receipt=JSON.parse(await readFile(filename,'utf8'));
      assert.equal(receipt.incomplete,false);
      assert.equal(receipt.coordinateSpace,'world');
      assert.equal(receipt.rootSource,'explodeRoot');
      assert.equal(receipt.sceneRootOptIn,false);
      assert.ok(receipt.meshes.length>0);
      assert.deepEqual(receipt.skippedMeshes,[]);
      console.log('PASS: '+mode+' browser exported '+state.visible+' visible pixels');
    }
  } finally {await browser.close();}
  const partial=join(out,'partial.json');
  assert.equal(await runCli(['--url',url+'partial','--out',partial,
    '--ready-flag','__IMG2THREEJS_READY__']),2);
  await assert.rejects(access(partial),{code:'ENOENT'});
  const diag=JSON.parse(await readFile(partial+'.incomplete.json','utf8'));
  assert.equal(diag.incomplete,true);
  assert.ok(diag.skippedMeshes.some(x=>x.reason==='partial-draw-range'));
  console.log('PASS: partial browser geometry withheld from successful receipts');
} finally {
  await new Promise(done=>server.close(done));
}
