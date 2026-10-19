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
const { GRID_SIZE, demoPixels, voxelize, nearestVisibleTile, findTilePath, buildBridge, tileHeight, exportThreeFactory, serializeWorld, deserializeWorld, previewWorldPixels } = (() => {
"""+world+"""
return {GRID_SIZE,demoPixels,voxelize,nearestVisibleTile,findTilePath,buildBridge,tileHeight,exportThreeFactory,serializeWorld,deserializeWorld,previewWorldPixels};
})();
const THREE=window.__THREE;
const OrbitControls=window.__OrbitControls;
"""+app+"""
window.__pocketTest={state:()=>({cells:cells.length,beacons:beacons.length,collected,scoutCell,scoutDestination,scoutVisible:scout.visible,scoutY:scout.position.y, dataSize:data.size}),
    send: cell=>routeScout(cell),step:(dt)=>animateScout(dt,false),path:(a,b)=>findTilePath(data,a,b),beaconCells:()=>beacons.map(b=>b.userData.cell),indexOf:cell=>cells.indexOf(cell),preview:()=>$('reference').getContext('2d').getImageData(0,0,28,28).data.length
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
    # Persist an entire numeric terrain and its relief; reload after a remix.
    with page.expect_download(timeout=5000) as download:
        page.locator('#save').click()
    saved=root/'dom-world-save.json'
    download.value.save_as(str(saved))
    import json
    receipt=json.loads(saved.read_text())
    check('world JSON saves version, terrain and relief', receipt['version']==1 and receipt['relief']==2 and len(receipt['world']['colors'])==784)
    page.locator('#remix').click()
    page.locator('#relief').fill('0.4')
    page.locator('#load').set_input_files(str(saved))
    page.wait_for_timeout(80)
    check('saved JSON restores relief and preview',page.locator('#relief-value').inner_text()=='2.0×' and page.locator('#source-label').inner_text()=='Restored world')
    check('saved JSON restores scout and beacons',page.evaluate('window.__pocketTest.state().beacons')==5 and page.evaluate('window.__pocketTest.state().scoutVisible'))
    # An uploaded transparent channel splits the island. A player can build and
    # undo a 4-connected bridge, preserving existing beacon collection.
    gap=root/'channel-test.png'
    island=Image.new('RGBA',(28,28),(0,0,0,0))
    for yy in range(28):
        for xx in list(range(11))+list(range(17,28)):
            island.putpixel((xx,yy),(80,150,95,255))
    island.save(gap)
    try:
        page.locator('#upload').set_input_files(str(gap))
        page.wait_for_timeout(160)
        check('channel image isolates two solid islands',page.evaluate('window.__pocketTest.state().cells')==616)
        anchor_a,anchor_b=7*28+10,7*28+17
        check('islands are disconnected before bridge',page.evaluate('([a,b])=>window.__pocketTest.path(a,b).length',[anchor_a,anchor_b])==0)
        page.evaluate('window.__pickBeacon=0')
        page.mouse.click(500,320)
        page.evaluate('delete window.__pickBeacon')
        check('existing beacon found before edit',page.evaluate('window.__pocketTest.state().collected')==1)
        page.locator('#bridge').click()
        check('bridge tool enabled with pressed state',page.locator('#bridge').get_attribute('aria-pressed')=='true')
        def click_cell(cell):
            page.evaluate('(cell)=>window.__pickTile=window.__pocketTest.indexOf(cell)',cell)
            page.mouse.click(500,320)
            page.evaluate('delete window.__pickTile')
        click_cell(anchor_a)
        check('first bridge anchor waits for second', 'First anchor set' in page.locator('#scout-status').inner_text())
        click_cell(anchor_b)
        check('new bridge adds six traversable tiles',page.evaluate('window.__pocketTest.state().cells')==622)
        check('scout can pathfind across bridge',page.evaluate('([a,b])=>window.__pocketTest.path(a,b).length',[anchor_a,anchor_b])>0)
        check('bridge keeps previously collected beacon',page.evaluate('window.__pocketTest.state().collected')==1)
        check('undo becomes available after edit',page.locator('#undo-bridge').is_enabled())
        with page.expect_download(timeout=5000) as download:
            page.locator('#save').click()
        saved_bridge=root/'bridge-world.json'
        download.value.save_as(str(saved_bridge))
        bridge_receipt=json.loads(saved_bridge.read_text())
        check('saved world includes six bridge tiles',sum(bridge_receipt['world']['visible'])==622)
        page.locator('#undo-bridge').click()
        check('undo restores island channel and previous beacon',page.evaluate('window.__pocketTest.state().cells')==616 and page.evaluate('window.__pocketTest.state().collected')==1)
        check('undo restores disconnected topology',page.evaluate('([a,b])=>window.__pocketTest.path(a,b).length',[anchor_a,anchor_b])==0)
        page.locator('#load').set_input_files(str(saved_bridge))
        page.wait_for_timeout(100)
        check('JSON restores built bridge offline',page.evaluate('window.__pocketTest.state().cells')==622)
        saved_bridge.unlink(missing_ok=True)
        page.locator('#bridge').click()
    finally:
        gap.unlink(missing_ok=True)
    # In-flight image decode must not overwrite a newly selected preset.
    slow_again=root/'slow-upload.png'
    Image.new('RGBA',(16,16),(230,45,25,255)).save(slow_again)
    try:
        page.locator('#upload').set_input_files(str(slow_again))
        page.locator('#remix').click()
        new_label=page.locator('#source-label').inner_text()
        page.wait_for_timeout(420)
        check('remix supersedes delayed image decode',page.locator('#source-label').inner_text()==new_label and new_label!='slow-upload.png')
    finally:
        slow_again.unlink(missing_ok=True)
    invalid=root/'dom-world-bad.json'
    invalid.write_text('not JSON')
    previous=page.locator('#source-label').inner_text()
    page.locator('#load').set_input_files(str(invalid))
    page.wait_for_timeout(80)
    check('invalid JSON leaves current world intact',page.locator('#source-label').inner_text()==previous and 'Invalid' in page.locator('#notice').inner_text())
    invalid.unlink(missing_ok=True)
    saved.unlink(missing_ok=True)
    check('no JS uncaught exceptions', not errs)
    print('RESULT',sum(1 for _,ok in checks if ok),'/',len(checks),'errors',errs)
    browser.close()
    if not all(ok for _,ok in checks):raise SystemExit(1)
