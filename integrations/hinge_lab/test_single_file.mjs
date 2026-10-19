#!/usr/bin/env node
/** Browser acceptance for the single HTML file (no HTTP server, CDN or backend). */
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright';

const output = resolve(process.env.HINGE_LAB_OUTPUT || 'hinge-lab-dist');
const path = join(output, 'Hinge-Lab-Standalone.html');
if (!existsSync(path)) throw new Error('run package_single_file.mjs first');
const raw = readFileSync(path, 'utf8');
assert.ok(raw.includes('data:image/jpeg;base64,'), 'photo must be embedded');
assert.ok(raw.includes('Bundled library and repository license notices'));
assert.ok(!raw.includes('<script src="bundle.js"'),
  'external bundle reference must be removed');

const browser = await chromium.launch({
  headless:true,
  args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl',
        '--ignore-gpu-blocklist','--disable-dev-shm-usage'],
});
const browserErrors = [], externalRequests = [];
try {
  const page = await browser.newPage({
    viewport:{width:1280,height:800}, deviceScaleFactor:1,
  });
  page.on('pageerror',e=>browserErrors.push(e.message));
  page.on('request',request=>{
    if (!request.url().startsWith('file:') &&
        !request.url().startsWith('data:') &&
        !request.url().startsWith('blob:')) {
      externalRequests.push(request.url());
    }
  });
  await page.goto(pathToFileURL(path).href,{waitUntil:'load'});
  await page.waitForFunction(()=>window.__hingeLabReady===true,null,{timeout:45000});
  const start = await page.evaluate(()=>window.__hingeLab.getStatus());
  assert.equal(start.triangles>0,true,'no generated WebGL triangles');
  assert.equal(await page.locator('input[type=range]').count(),4);
  assert.deepEqual(start.angles,{
    'back-flap':0,'front-flap':0,'left-flap':0,'right-flap':0
  });
  await page.locator('#pose').click();
  assert.equal(await page.evaluate(()=>window.__hingeLab.getStatus().angles['front-flap']),-65);
  await page.locator('#rest').click();
  await page.evaluate(()=>window.__hingeLab.setFold('back-flap',180));
  await page.locator('#check').click();
  const check = await page.evaluate(()=>window.__hingeLab.getStatus().lastEvaluation);
  assert.equal(check.status,'collision',
    'generated floor must block complete 180-degree rigid fold');
  assert.equal(check.targets[0].id,'carton floor');
  assert.ok(check.targets[0].collision.overlap>0);
  assert.ok(check.evaluationMs>=0);
  await page.locator('#rest').click();
  await page.locator('#obstacle-enabled').check();
  await page.evaluate(()=>window.__hingeLab.setFold('back-flap',90));
  await page.locator('#check').click();
  const injected = await page.evaluate(()=>window.__hingeLab.getStatus().lastEvaluation);
  assert.equal(injected.targets.find(t=>t.id==='test obstacle')?.status,'collision');
  assert.ok(injected.sampledCollisions>0);
  await page.screenshot({path:join(output,'lab-single-file-tested.png')});

  const mobile = await browser.newPage({
    viewport:{width:390,height:844},deviceScaleFactor:1,
  });
  mobile.on('pageerror',e=>browserErrors.push(e.message));
  mobile.on('request',request=>{
    if (!request.url().startsWith('file:') &&
        !request.url().startsWith('data:') &&
        !request.url().startsWith('blob:')) {
      externalRequests.push(request.url());
    }
  });
  await mobile.goto(pathToFileURL(path).href,{waitUntil:'load'});
  await mobile.waitForFunction(()=>window.__hingeLabReady===true,null,{timeout:45000});
  const dimensions = await mobile.evaluate(()=>({
    width:window.innerWidth, scrollWidth:document.documentElement.scrollWidth,
    canvasHeight:document.getElementById('stage').getBoundingClientRect().height,
    rendered:window.__hingeLab.getStatus().triangles>0,
  }));
  assert.ok(dimensions.scrollWidth<=dimensions.width+2,
    'mobile single-file page must have no horizontal overflow');
  assert.ok(dimensions.canvasHeight>180&&dimensions.rendered);
  assert.deepEqual(browserErrors,[],'single-file browser runtime errors');
  assert.deepEqual(externalRequests,[],'single-file viewer must remain offline');
  console.log('HINGE_SINGLE_BROWSER_PASS:',JSON.stringify({
    fourControls:true,generatedWebGL:true,collisionCheck:true,
    interactive:true,mobile:dimensions,externalRequests:0,browserErrors:0,
  }));
} finally {
  await browser.close();
}
