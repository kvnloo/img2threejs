#!/usr/bin/env node
/** Builds and validates an offline hinged-carton lab using real emitted factory code.
 * Research integration only. No network access required at runtime.
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync,
  rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import { chromium } from 'playwright';

const integration = dirname(fileURLToPath(import.meta.url));
const root = resolve(integration, '../..');
const output = resolve(process.env.HINGE_LAB_OUTPUT || join(root, 'hinge-lab-dist'));
const reference = process.env.HINGE_REFERENCE_PHOTO;
if (!reference) throw new Error('HINGE_REFERENCE_PHOTO is required for the licensed example');
if (!existsSync(reference)) throw new Error('missing credited reference JPEG');
const referenceBytes = readFileSync(reference);
if (referenceBytes.length < 25000 ||
    referenceBytes[0] !== 0xff || referenceBytes[1] !== 0xd8) {
  throw new Error('reference must be an actual JPEG, not a placeholder');
}
const digest = createHash('sha256').update(referenceBytes).digest('hex');
const work = mkdtempSync(join(root, '.hinge-lab-build-'));
let browser;
try {
  mkdirSync(output, {recursive:true});
  execFileSync('python3', [join(root,'forge/tests/emit_hinge_photo_fixture.py'),
    join(work, 'factory.ts')], {cwd:root,stdio:'inherit'});
  execFileSync(join(root,'node_modules/.bin/tsc'), [
    '--noEmit','--strict','--skipLibCheck','--target','es2022',
    '--module','esnext','--moduleResolution','bundler',
    '--lib','es2022,dom',join(work,'factory.ts')
  ], {cwd:root,stdio:'inherit'});
  copyFileSync(join(integration, 'app.mjs'),join(work,'app.mjs'));
  copyFileSync(join(root,'forge/tests/hinge_sweep_collision.mjs'),
    join(work,'hinge_sweep_collision.mjs'));
  copyFileSync(join(integration,'index.html'),join(output,'index.html'));
  copyFileSync(join(work,'factory.ts'),join(output,'createOpenFoldingCartonModel.ts'));
  copyFileSync(reference,join(output,'reference.jpg'));
  await build({
    entryPoints:[join(work,'app.mjs')],
    outfile:join(output,'bundle.js'),
    bundle:true,format:'iife',platform:'browser',
    target:'es2022',minify:true,logLevel:'warning',
  });
  const manifest = {
    kind:'img2threejs.hinge-lab-offline',
    revision:1,
    generatedFactory:'forge/tests/emit_hinge_photo_fixture.py',
    generatedSource:'createOpenFoldingCartonModel.ts',
    generatedSourceSha256:createHash('sha256').update(
      readFileSync(join(output,'createOpenFoldingCartonModel.ts'))).digest('hex'),
    framework:'three@0.180.0',
    reference:{
      url:'https://commons.wikimedia.org/wiki/File:Box.agr.jpg',
      creator:'Arnold Reinhold',
      license:'CC BY-SA 3.0',
      licenseUrl:'https://creativecommons.org/licenses/by-sa/3.0/',
      sha256:digest,
    },
    constraints:[
      'procedural proxy manually authored from reference, not image-derived geometry',
      'collision certificate only for supported stationary rigid boxes',
      'photographic fidelity unverified; no remote assets or accounts',
    ],
  };
  writeFileSync(join(output,'manifest.json'),
    JSON.stringify(manifest,null,2)+'\n');
  const text = 'Hinge Lab (experimental)\n\n' +
    'Open index.html in a browser. All model and Three.js code is in bundle.js.\n' +
    'The generated editable TypeScript is createOpenFoldingCartonModel.ts.\n' +
    'The included reference.jpg is a CC BY-SA 3.0 work by Arnold Reinhold.\n' +
    'See manifest.json for source, license, SHA-256, and limitations.\n' +
    'No internet connection is needed to use the app.\n';
  writeFileSync(join(output,'README.txt'),text);

  browser = await chromium.launch({headless:true,args:[
    '--use-gl=angle','--use-angle=swiftshader','--enable-webgl',
    '--ignore-gpu-blocklist','--disable-dev-shm-usage',
  ]});
  const page = await browser.newPage({viewport:{width:1365,height:870},deviceScaleFactor:1,
    acceptDownloads:true});
  const errors = [], remote = [];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{
    if (!r.url().startsWith('file:') && !r.url().startsWith('data:') &&
        !r.url().startsWith('blob:')) remote.push(r.url());
  });
  await page.goto(pathToFileURL(join(output,'index.html')).href,{waitUntil:'load'});
  await page.waitForFunction(()=>window.__hingeLabReady===true,null,{timeout:40000});
  await page.waitForFunction(()=>window.__hingeLab.getStatus().drawCalls>0,null,{timeout:30000});
  assert.equal(await page.locator('input[type=range]').count(),4);
  assert.ok(readFileSync(join(output,'createOpenFoldingCartonModel.ts'),'utf8')
    .includes('export function createOpenFoldingCartonModel('));
  assert.deepEqual(await page.evaluate(()=>window.__hingeLab.getStatus().angles),
    {'back-flap':0,'front-flap':0,'left-flap':0,'right-flap':0});
  await page.screenshot({path:join(output,'lab-flat.png')});
  await page.locator('#pose').click();
  assert.deepEqual(await page.evaluate(()=>window.__hingeLab.getStatus().angles),
    {'back-flap':22,'front-flap':-65,'left-flap':-24,'right-flap':32});
  await page.screenshot({path:join(output,'lab-photo-pose.png')});
  await page.locator('#rest').click();
  await page.locator('#obstacle-enabled').check();
  await page.evaluate(()=>window.__hingeLab.setFold('back-flap',90));
  await page.locator('#check').click();
  const hit = await page.evaluate(()=>window.__hingeLab.getStatus());
  assert.equal(hit.lastEvaluation?.status,'collision');
  assert.ok(hit.lastEvaluation?.collision?.overlap>0);
  await page.screenshot({path:join(output,'lab-collision.png')});
  await page.evaluate(()=>window.__hingeLab.setFold('back-flap',-90));
  await page.locator('#check').click();
  assert.equal(await page.evaluate(()=>window.__hingeLab.getStatus().lastEvaluation?.status),
    'certified-clear');
  await page.locator('#collision-part').selectOption('right-flap');
  await page.evaluate(()=>window.__hingeLab.setFold('right-flap',90));
  await page.locator('#check').click();
  assert.equal(await page.evaluate(()=>window.__hingeLab.getStatus().lastEvaluation?.status),
    'collision');
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('#export').click(),
  ]);
  assert.equal(download.suggestedFilename(),'hinge-lab-pose.json');
  const posePath = await download.path();
  const payload = JSON.parse(readFileSync(posePath,'utf8'));
  assert.equal(payload.format,'img2threejs.hinge-lab-pose.v1');
  assert.equal(payload.anglesDegrees['right-flap'],90);
  await page.locator('#rest').click();
  assert.equal(await page.evaluate(()=>window.__hingeLab.getStatus().angles['right-flap']),0);
  await page.locator('#import-file').setInputFiles({
    name:'exported-pose.json',mimeType:'application/json',
    buffer:Buffer.from(readFileSync(posePath))
  });
  await page.waitForFunction(()=>
    window.__hingeLab.getStatus().angles['right-flap']===90);
  assert.equal(await page.locator('#status-title').textContent(),'Pose imported');
  await page.locator('#import-file').setInputFiles({
    name:'invalid-pose.json',mimeType:'application/json',
    buffer:Buffer.from(JSON.stringify({
      format:'img2threejs.hinge-lab-pose.v1',
      anglesDegrees:{...payload.anglesDegrees,'right-flap':999}
    }))
  });
  await page.waitForFunction(()=>document.getElementById('status-title').textContent==='Import rejected');
  assert.equal(await page.evaluate(()=>window.__hingeLab.getStatus().angles['right-flap']),90);
  const mobile = await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1});
  mobile.on('pageerror',e=>errors.push(e.message));
  await mobile.goto(pathToFileURL(join(output,'index.html')).href,{waitUntil:'load'});
  await mobile.waitForFunction(()=>window.__hingeLabReady===true,null,{timeout:40000});
  const metrics = await mobile.evaluate(()=>({
    viewport:window.innerWidth,
    pageWidth:document.documentElement.scrollWidth,
    visible:document.getElementById('stage').getBoundingClientRect().height>180,
  }));
  assert.ok(metrics.pageWidth<=metrics.viewport+2,
    'mobile layout overflows horizontally: '+JSON.stringify(metrics));
  assert.equal(metrics.visible,true);
  await mobile.screenshot({path:join(output,'lab-mobile.png'),fullPage:true});
  assert.deepEqual(remote,[],'offline lab requested remote resources');
  assert.deepEqual(errors,[],'runtime browser errors');
  console.log('HINGE_LAB_PASS:',JSON.stringify({
    library:'Three.js r180',panels:4,
    interactions:['photo preset','reset','positive collision','reverse certified-clear',
      'right-flap collision','export/import pose JSON','reject malformed pose','mobile layout'],
    screenshotFiles:['lab-flat.png','lab-photo-pose.png',
      'lab-collision.png','lab-mobile.png'],
    offlineRequests:remote.length,
    output,referenceSha256:digest,
  }));
} finally {
  if (browser) await browser.close();
  rmSync(work,{recursive:true,force:true});
}
