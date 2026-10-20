"""Optional DOM regression test with a fake THREE binding. Not a WebGL visual test."""
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image
import os
import re
import shutil

root=Path(__file__).resolve().parents[1]
html=(root/'index.html').read_text()
html=re.sub(r'<script type="importmap">.*?</script>', '', html, flags=re.S)
html=re.sub(r'<script type="module" src="./app.mjs"></script>', '', html)
world=re.sub(r'(?m)^export ', '', (root/'world-data.mjs').read_text())
app=re.sub(r'(?ms)^import\s.*?;\n', '', (root/'app.mjs').read_text())
source="""
const { GRID_SIZE, demoPixels, voxelize, nearestVisibleTile, findTilePath, buildBridge, nextBeaconRoute, validateAdventure, tileHeight, exportThreeFactory, serializeWorld, deserializeWorld, previewWorldPixels } = (() => {
"""+world+"""
return {GRID_SIZE,demoPixels,voxelize,nearestVisibleTile,findTilePath,buildBridge,nextBeaconRoute,validateAdventure,tileHeight,exportThreeFactory,serializeWorld,deserializeWorld,previewWorldPixels};
})();
const THREE=window.__THREE;
const OrbitControls=window.__OrbitControls;
"""+app+"""
window.__pocketTest={terrain:()=>world,pickBeacons:indices=>{window.__pickBeaconObjects=indices.map(i=>beacons[i]);},state:()=>({cells:cells.length,beacons:beacons.length,collected,scoutCell,scoutDestination,scoutVisible:scout.visible,scoutY:scout.position.y, dataSize:data.size}),
    bridge:cell=>bridgeClick(cell),validPassport:()=>{try{serializeWorld(data,relief,saveAdventure());return true}catch{return false}},reset:cell=>resetScout(cell),navigation:()=>({scoutCell,scoutDestination,scoutFraction,queue:[...scoutQueue],x:scout.position.x,z:scout.position.z}),send: cell=>routeScout(cell),step:(dt)=>animateScout(dt,false),path:(a,b)=>findTilePath(data,a,b),beaconCells:()=>beacons.map(b=>b.userData.cell),indexOf:cell=>cells.indexOf(cell),preview:()=>$('reference').getContext('2d').getImageData(0,0,28,28).data.length
};
"""

with sync_playwright() as p:
    executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium')
    browser=p.chromium.launch(executable_path=executable,headless=True,args=['--no-sandbox'])
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
    page.evaluate('window.__oldTerrain=window.__pocketTest.terrain()')
    page.locator('#remix').click()
    check('replaced terrain releases instance buffers, geometry and material',
          page.evaluate('window.__oldTerrain.disposed===true && window.__oldTerrain.geometry.disposed===true && window.__oldTerrain.material.disposed===true'))
    page.evaluate('delete window.__oldTerrain')
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
    # The compass should guide instead of teleporting, with ordinary scout/beacon state.
    page.locator('#hint').click()
    hint_status=page.locator('#scout-status').inner_text()
    check('compass starts a real scout path', 'Scout hiking' in hint_status)
    beacon_goal=page.evaluate('window.__pocketTest.state().scoutDestination')
    page.evaluate('() => { for(let i=0;i<200;i++)window.__pocketTest.step(.4); }')
    journal_before=page.evaluate('window.__pocketTest.state()')
    check('compass reaches and collects beacon',journal_before['collected']>=1 and beacon_goal>=0)
    with page.expect_download(timeout=5000) as download:
        page.locator('#save').click()
    saved=root/'dom-world-save.json'
    download.value.save_as(str(saved))
    import json
    receipt=json.loads(saved.read_text())
    check('world JSON v2 saves adventure, terrain and relief', receipt['version']==2 and receipt['relief']==2 and len(receipt['world']['colors'])==784 and receipt['adventure']['scoutCell']==journal_before['scoutCell'] and len(receipt['adventure']['collectedCells'])==journal_before['collected'])
    page.locator('#remix').click()
    page.locator('#relief').fill('0.4')
    page.locator('#load').set_input_files(str(saved))
    page.wait_for_timeout(80)
    check('saved JSON restores relief and preview',page.locator('#relief-value').inner_text()=='2.0×' and page.locator('#source-label').inner_text()=='Restored world')
    restored_status=page.evaluate('window.__pocketTest.state()')
    check('saved JSON restores scout and beacons',restored_status['beacons']==5 and restored_status['scoutVisible'])
    check('saved v2 adventure restores exact scout tile and collected count',restored_status['scoutCell']==journal_before['scoutCell'] and restored_status['collected']==journal_before['collected'])
    # V1 terrain remains readable but starts a new adventure.
    legacy=root/'dom-world-v1.json'
    legacy_json=dict(receipt)
    legacy_json.pop('adventure')
    legacy_json['version']=1
    legacy.write_text(json.dumps(legacy_json))
    page.locator('#load').set_input_files(str(legacy))
    page.wait_for_timeout(70)
    check('legacy v1 terrain still loads and resets adventure',page.evaluate('window.__pocketTest.state().collected')==0)
    legacy.unlink(missing_ok=True)
    # Tampered bookmark must not mutate the active world.
    tamper=root/'dom-world-tamper.json'
    invalid_json=dict(receipt)
    invalid_json['adventure']=dict(receipt['adventure'])
    invalid_json['adventure']['collectedCells']=[783,783]
    tamper.write_text(json.dumps(invalid_json))
    previous=page.evaluate('window.__pocketTest.state()')
    page.locator('#load').set_input_files(str(tamper))
    page.wait_for_timeout(70)
    check('tampered v2 adventure refused without replacing world',page.evaluate('window.__pocketTest.state()')==previous and 'Invalid' in page.locator('#notice').inner_text())
    tamper.unlink(missing_ok=True)
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
    # Retargeting must finish the current cardinal hop before making a turn.
    page.locator('#remix').click()
    turn = page.evaluate("""() => {
        const t = window.__pocketTest;
        t.reset(0); t.send(1); t.step(.125);
        const before = t.navigation();
        t.send(28);
        const after = t.navigation();
        for (let i=0; i<100; i++) t.step(.4);
        return {before, after, final:t.navigation()};
    }""")
    check('retarget preserves the current cardinal hop',
          turn['after']['scoutDestination']==1 and turn['after']['scoutFraction']==turn['before']['scoutFraction'])
    check('retarget eventually reaches the new requested tile',turn['final']['scoutCell']==28)
    returned = page.evaluate("""() => {
        const t = window.__pocketTest;
        t.reset(0); t.send(1); t.step(.125); t.send(0);
        for (let i=0; i<100; i++) t.step(.4);
        return t.navigation();
    }""")
    check('retargeting to the last completed tile returns there',returned['scoutCell']==0)

    # A tap is one primary contact with no drag, cancellation or pinch history.
    def gesture(events):
        return page.evaluate("""events => {
            window.__pocketTest.reset(0);
            window.__pickTile=1;
            const canvas=document.getElementById('viewport');
            for (const [type,extra] of events) {
                canvas.dispatchEvent(new PointerEvent(type, {
                    bubbles:true, pointerId:1, isPrimary:true, button:0,
                    clientX:500, clientY:320, ...extra,
                }));
            }
            delete window.__pickTile;
            return window.__pocketTest.navigation().scoutDestination;
        }""",events)
    for label, events in [
        ('right-button orbit is not a terrain tap', [('pointerdown',{'button':2}),('pointerup',{'button':2})]),
        ('drag returning to its origin is not a terrain tap', [('pointerdown',{}),('pointermove',{'clientX':520}),('pointermove',{}),('pointerup',{})]),
        ('second touch cancels the first tap candidate', [('pointerdown',{}),('pointerdown',{'pointerId':2,'isPrimary':False}),('pointerup',{'pointerId':2,'isPrimary':False}),('pointerup',{})]),
        ('mismatched pointer cannot finish a tap', [('pointerdown',{}),('pointerup',{'pointerId':2})]),
        ('cancelled pointer cannot finish a tap', [('pointerdown',{}),('pointercancel',{}),('pointerup',{})]),
        ('lost pointer capture cancels a tap', [('pointerdown',{}),('lostpointercapture',{}),('pointerup',{})]),
    ]:
        check(label, gesture(events)==-1)
    check('single primary touch still navigates',gesture([
        ('pointerdown',{'pointerType':'touch'}),('pointerup',{'pointerType':'touch'})])==1)

    # The receipt domain permits 3.0 relief: the HTML control must not clamp it.
    relief_receipt = dict(receipt, relief=3.0)
    page.locator('#load').set_input_files({
        'name':'relief.json', 'mimeType':'application/json',
        'buffer':json.dumps(relief_receipt).encode(),
    })
    page.wait_for_timeout(70)
    check('valid maximum relief remains editable without clamping',
          page.locator('#relief').input_value()=='3' and page.locator('#relief-value').inner_text()=='3.0×')
    # Bridging a two-cell image adds terrain and must fill missing beacon slots.
    sparse_world = dict(receipt['world'], visible=[int(i in (10,17)) for i in range(784)])
    sparse = dict(receipt, version=1, world=sparse_world)
    sparse.pop('adventure', None)
    page.locator('#load').set_input_files({
        'name':'sparse.json', 'mimeType':'application/json',
        'buffer':json.dumps(sparse).encode(),
    })
    page.wait_for_timeout(70)
    check('two-cell source has two beacons and a valid passport',
          page.evaluate('window.__pocketTest.state().beacons')==2 and page.evaluate('window.__pocketTest.validPassport()'))
    page.evaluate('() => {window.__pocketTest.bridge(10); window.__pocketTest.bridge(17);}')
    check('bridge adds missing beacon slots without breaking saves',
          page.evaluate('window.__pocketTest.state().beacons')==5 and page.evaluate('window.__pocketTest.validPassport()'))
    page.locator('#undo-bridge').click()
    check('undo restores the sparse-world beacon count and valid passport',
          page.evaluate('window.__pocketTest.state().beacons')==2 and page.evaluate('window.__pocketTest.validPassport()'))
    # Three.js raycasts invisible objects too: hidden collected beacons must not
    # occlude a still-visible beacon further along the ray.
    page.locator('#remix').click()
    page.evaluate('window.__pocketTest.pickBeacons([0])')
    page.mouse.click(500, 320)
    check('direct beacon tap still collects one beacon',page.evaluate('window.__pocketTest.state().collected')==1)
    page.evaluate('window.__pocketTest.pickBeacons([0,1])')
    page.mouse.click(500, 320)
    check('collected beacon cannot occlude a visible beacon',page.evaluate('window.__pocketTest.state().collected')==2)
    collected_before=page.evaluate('window.__pocketTest.state().collected')
    page.evaluate('window.__pocketTest.pickBeacons([0,1])')
    page.mouse.click(500, 320)
    check('collected beacon hits cannot count twice',page.evaluate('window.__pocketTest.state().collected')==collected_before)
    page.evaluate('delete window.__pickBeaconObjects')
    check('no JS uncaught exceptions', not errs)
    print('RESULT',sum(1 for _,ok in checks if ok),'/',len(checks),'errors',errs)
    browser.close()
    if not all(ok for _,ok in checks):raise SystemExit(1)
