"""Optional DOM regression test with a fake THREE binding. Not a WebGL visual test."""
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image
import re

root=Path(__file__).resolve().parents[1]
html=(root/'index.html').read_text()
html=re.sub(r'<script type="importmap">.*?</script>', '', html, flags=re.S)
html=re.sub(r'<script type="module" src="./app.mjs"></script>', '', html)
world=re.sub(r'(?m)^export ', '', (root/'world-data.mjs').read_text())
app='\n'.join(line for line in (root/'app.mjs').read_text().splitlines() if not line.startswith('import '))
source="""
const { GRID_SIZE, demoPixels, voxelize, nearestVisibleTile, findTilePath, tileHeight, exportThreeFactory } = (() => {
"""+world+"""
return {GRID_SIZE,demoPixels,voxelize,nearestVisibleTile,findTilePath,tileHeight,exportThreeFactory};
})();
const THREE=window.__THREE;
const OrbitControls=window.__OrbitControls;
"""+app+"""
window.__pocketTest={state:()=>({cells:cells.length,beacons:beacons.length,collected,scoutCell,scoutDestination,scoutVisible:scout.visible,scoutY:scout.position.y, dataSize:data.size}),
    send: cell=>routeScout(cell),step:(dt)=>animateScout(dt,false),path:(a,b)=>findTilePath(data,a,b),beaconCells:()=>beacons.map(b=>b.userData.cell),preview:()=>$('reference').getContext('2d').getImageData(0,0,28,28).data.length
};
"""

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1100,'height':740},accept_downloads=True)
    errs=[]
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.set_content(html)
    page.add_script_tag(content=(root/'tests/mock-three.js').read_text())
    page.evaluate('source => new Function(source)()', source)
    page.wait_for_timeout(150)
    checks=[]
    def check(label,ok):
        checks.append((label,bool(ok)))
        print('PASS' if ok else 'FAIL',label)
    state=page.evaluate('window.__pocketTest.state()')
    check('init visible 28x28 world',state['cells']==784 and state['beacons']==5 and state['scoutVisible'])
    check('preview RGBA',page.evaluate('window.__pocketTest.preview()')==28*28*4)
    page.locator('#remix').click()
    check('remix label', page.locator('#source-label').inner_text()=='Emerald valley')
    page.locator('#night').click()
    check('night mode aria state',page.locator('#night').get_attribute('aria-pressed')=='true')
    page.locator('#night').click()
    page.locator('#orbit').click()
    check('orbit mode aria state',page.locator('#orbit').get_attribute('aria-pressed')=='true')
    page.locator('#relief').fill('2')
    check('relief update',page.locator('#relief-value').inner_text()=='2.0×')
    start=page.evaluate('window.__pocketTest.state().scoutCell')
    target=page.evaluate('window.__pocketTest.beaconCells()[0]')
    route=page.evaluate('([a,b])=>window.__pocketTest.path(a,b)', [start,target])
    page.evaluate('({target,len}) => { window.__pocketTest.send(target);for(let i=0;i<len+1;i++)window.__pocketTest.step(.4) }',{'target':target,'len':len(route)})
    state=page.evaluate('window.__pocketTest.state()')
    check('scout reaches target & collects beacon',state['scoutCell']==target and state['collected']>=1)
    # Synthetic transparent image exercises real File→Bitmap→Canvas→Voxel pipeline.
    transparent=root/'transparent-test.png'
    Image.new('RGBA',(16,16),(0,0,0,0)).save(transparent)
    try:
        page.locator('#upload').set_input_files(str(transparent))
        page.wait_for_timeout(450)
        state=page.evaluate('window.__pocketTest.state()')
        check('transparent uploaded image creates zero visible terrain',state['cells']==0 and not state['scoutVisible'] and state['beacons']==0)
        check('empty alpha state has explanatory status','No visible terrain' in page.locator('#scout-status').inner_text())
    finally:
        transparent.unlink(missing_ok=True)
    page.locator('#remix').click()
    state=page.evaluate('window.__pocketTest.state()')
    check('remix restores playable world',state['cells']==784 and state['scoutVisible'] and state['beacons']==5)
    # Exercise the actual pointerup+raycast path rather than only calling the route helper.
    target=page.evaluate('window.__pocketTest.beaconCells()[1]')
    page.evaluate('window.__pickTile=0')
    page.mouse.click(500, 320)
    check('pointer-to-terrain click enters scout navigation', 'Scout hiking' in page.locator('#scout-status').inner_text())
    page.evaluate('delete window.__pickTile')

    # Source imports may resolve out of order; newest selection must win.
    slow=root/'slow-upload.png'
    fast=root/'fast-upload.png'
    huge=root/'oversized-upload.png'
    Image.new('RGBA',(16,16),(200,0,0,255)).save(slow)
    Image.new('RGBA',(16,16),(0,200,0,255)).save(fast)
    Image.new('RGBA',(16,16),(5,5,5,255)).save(huge)
    try:
        page.evaluate("""() => {
          const original = window.createImageBitmap;
          window.__originalImageBitmap = original;
          window.__closedLargeBitmap=0;
          window.createImageBitmap = async (file) => {
            if(file.name==='slow-upload.png') await new Promise(ok => setTimeout(ok,300));
            if(file.name==='oversized-upload.png') return {width:7000,height:7000,close(){window.__closedLargeBitmap++}};
            return original(file);
          };
        }""")
        page.locator('#upload').set_input_files(str(slow))
        page.locator('#upload').set_input_files(str(fast))
        page.wait_for_timeout(550)
        check('latest uploaded image wins async race',page.locator('#source-label').inner_text()=='fast-upload.png')
        prev=page.evaluate('window.__pocketTest.state().cells')
        page.locator('#upload').set_input_files(str(huge))
        page.wait_for_timeout(120)
        check('decoded 49 MP image refused with bitmap release',
              page.evaluate('window.__closedLargeBitmap')==1 and prev==page.evaluate('window.__pocketTest.state().cells'))
    finally:
        for f in (slow,fast,huge):f.unlink(missing_ok=True)
    with page.expect_download(timeout=5000) as download:
        page.locator('#export').click()
    generated=root/'dom-export-test.mjs'
    download.value.save_as(str(generated))
    contents=generated.read_text()
    generated.unlink(missing_ok=True)
    check('browser export creates standalone factory',"export function buildPocketWorld" in contents and 'fetch(' not in contents)
    check('no JS uncaught exceptions', not errs)
    print('RESULT',sum(1 for _,ok in checks if ok),'/',len(checks),'errors',errs)
    browser.close()
    if not all(ok for _,ok in checks):raise SystemExit(1)
