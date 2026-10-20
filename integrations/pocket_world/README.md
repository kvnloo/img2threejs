# Pocket World (experimental)

Turn an image into a 28 × 28 voxel island, guide a scout, collect beacons, build
undoable bridges, and save an adventure or export a standalone `THREE.Group`.
Three procedural postcards work without an uploaded image.

This is **artistic pixel relief, not depth estimation, photogrammetry or measured
3D reconstruction**. It is an optional integration; the core generator and its
quality gates are unchanged. Images stay in the browser. The preview loads pinned
Three.js r169 modules from jsDelivr; no meshes, textures or art packs are downloaded.

## Run

From the repository root:

```sh
python3 -m http.server 8000
# Open http://localhost:8000/integrations/pocket_world/
```

The preview needs internet access for its Three.js modules. The exported
`pocket-world.mjs` imports only `three`: install that package in your target app,
call `buildPocketWorld()`, and add your own lights and camera. Its geometry and
colors are embedded numbers, with no remote asset dependency.

## Controls and saves

Drag to orbit, scroll or pinch to zoom, and tap terrain to guide the scout. Only a
single primary contact counts as a tap; right-button gestures, pinches, cancelled
contacts and drags do not collect treasure or edit terrain. The compass selects a
reachable, uncollected beacon. Retargeting finishes the current grid edge before
turning, rather than cutting diagonally across invisible cells.

The scout uses stable binary-heap A*. The compass uses one slope-aware Dijkstra
search and reuses its route. Equal-cost targets prefer the lower tile ID. Neither
planner invents a route over invisible cells. Brightness is an artistic height
proxy, not measured elevation. Direct beacon taps also collect treasure; collected
beacons no longer intercept hits on visible ones.

To build a bridge, select two visible anchors. Only transparent cells are filled;
existing visible colors and heights are preserved. Up to 12 edits can be undone.
Replaced terrain releases its instance buffers, geometry and material.
Surviving beacons retain their identities and progress, and new beacon slots are
filled when bridges expand a sparse island. Undo relocates a scout whose tile
vanished. New imports, remixes and edits supersede older asynchronous imports.

JSON v2 passports preserve numeric terrain, relief, the scout's last completed
tile, beacon locations and collected progress. Save mid-hike to resume from the
last reached tile. Legacy v1 terrain receipts start a fresh hunt. Empty worlds
have no scout or beacons. Both formats require a 28 × 28 grid and accept relief
from 0 to 3; invalid or oversized receipts are rejected before world replacement.

Invisible source RGB and derived heights are zeroed during sampling, save, load
and preview. Older receipts containing hidden colors remain readable, but those
fields are normalized without modifying visible tiles or the original file.
Images are center-cropped and downsampled. Limits: 12 MB per image, 36 megapixels
after decoding, and 128 KB per JSON receipt. Reduced-motion settings remove scout
hopping; this is not a claim of physical-device performance.

## Verify

```sh
node --test integrations/pocket_world/world-data.test.mjs
node --check integrations/pocket_world/app.mjs
# Optional synthetic CPU benchmark, not a GPU or mobile frame-time measurement:
node integrations/pocket_world/tests/bench_pathfinding.mjs
```

The optional interaction suite requires Python, Playwright, Pillow and Chromium:

```sh
python3 integrations/pocket_world/tests/dom_smoke.py
```

Set `CHROMIUM_EXECUTABLE` to select a browser, or use a Chromium installation
recognized by Playwright. This suite uses mocked Three.js to test uploads,
bookmarks, movement, gestures, bridge/undo and downloads. It is **not WebGL proof**.

`.github/workflows/pocket-world-webgl.yml` runs the data suite on Node 18 and 22
before installing isolated, pinned browser-test dependencies and running the
mocked interaction suite.
`tests/real_webgl_smoke.mjs` runs the actual app and OrbitControls, checks rendered
pixels and adventure round trips, checks stable GPU buffer counts across 12
remixes, and exercises touch, pinch and landscape in mobile emulation. Screenshots
and machine-readable receipts are CI artifacts.
Read-only observers exist only in the test bundle, not the shipped preview.

Browser smoke does not establish source-photo reconstruction fidelity or physical
Android/iOS gesture and performance acceptance. Those remain separate checks.

## Scope

Keep this downstream experiment separate from the core pipeline. Integration into
the Showcase or a future scene-to-world workflow requires a maintainer scope
decision; a passing game test does not advance a reconstruction quality gate.
