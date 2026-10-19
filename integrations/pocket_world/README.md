# Pocket World (experimental)

A small, playful image-to-Three.js experiment: bring a picture, explore a colorful 28 × 28 voxel relief, send a glowing scout along deterministic A* paths, **build reversible 4-connected bridges across transparent islands**, use the smart compass to reach nearby beacons, collect five treasures, change the lighting, then save/reload a complete adventure passport or **export a standalone code-only `THREE.Group` factory**. Three hand-coded procedural color postcards work without uploading a reference.

This is an **artistic pixel-relief toy**, **not** photogrammetry, depth estimation, measured 3D reconstruction, or a replacement for img2threejs's quality-gated pipeline. It is isolated from the core. No image, reference file, mesh, or texture is sent to a server. The browser loads Three.js r169 from jsDelivr; generated factory modules only import a local `three` package and embed numeric colors/heights.

## Try

From the repository root:

```sh
python3 -m http.server 8000
# open http://localhost:8000/integrations/pocket_world/
```

An internet connection is required for the preview's pinned Three.js modules. For the exported `pocket-world.mjs`, install `three` in the target app and call `buildPocketWorld()` to obtain a `THREE.Group`. Add your own lights and camera. Exported worlds have no remote asset dependencies.

## Test

```sh
node --test integrations/pocket_world/world-data.test.mjs
node --check integrations/pocket_world/app.mjs
# Optional CPU-local timings; output is also attached to the WebGL CI run:
node integrations/pocket_world/tests/bench_pathfinding.mjs
```

An optional DOM-interaction smoke test runs in headless Chromium with a mocked Three.js runtime (requires `python3` with `playwright` and `Pillow` installed):

```sh
python3 integrations/pocket_world/tests/dom_smoke.py
```

It covers real browser image decoding, async upload race handling, pointer controls, scout movement, bridge edits, invalid adventure bookmarks, legacy-v1 compatibility, v2 save/reload and downloadable exports. **This mock test alone does not verify WebGL rendering or Three.js import-map/CDN loading.**

A separate opt-in GitHub Actions workflow, `.github/workflows/pocket-world-webgl.yml`, installs pinned `three@0.169.0`, Playwright and esbuild into a runner temporary directory, then executes `tests/real_webgl_smoke.mjs` against a real Chromium WebGL page. It checks visible colored framebuffer pixels, live compass navigation and actual v2 download/reload. The preview itself still loads r169 from jsDelivr; the smoke bundles that exact version locally to avoid relying on a public CDN at test time. This is visual smoke evidence, **not** proof of fidelity to a photographed object.

Node 18+ works for the pure-data tests. Browser interaction requires modern WebGL and import-map support; mobile tap/drag/pinch are supported. Images are center-cropped and downsampled to 28 × 28 RGBA cells. This limits detail and intentionally avoids claims of true 3D reconstruction.

World JSON v2 now includes a validated **adventure passport**: the scout's last completed tile, the five beacon locations, and which beacons have already been collected. Save mid-hike to resume safely from the last reached tile; saving an empty image records a no-scout/zero-beacon state. Legacy v1 terrain-only receipts still load and start a fresh treasure hunt. Both versions hold only bounded, validated 28 × 28 numeric color/height/visibility arrays and relief, not the original source image. **Invisible source pixels are scrubbed**: their RGB and derived height are zeroed during sampling, save, load and preview. This prevents fully transparent source RGB from leaking into a portable passport. Older v1 receipts containing hidden colors still import, but their hidden fields are normalized without modifying visible tiles or the original loaded file. Receipts are capped at 128 KB and reject mismatched, invisible, duplicate or fabricated bookmark coordinates. A newer world, bridge edit or photo selection supersedes older in-flight imports.

Build a bridge by selecting two visible tiles, even across disconnected islands. The app fills only transparent cells along an orthogonal corridor, interpolating their visual height between anchors, and leaves all original color/height evidence unchanged. Bridges can be undone (up to 12 snapshots), saved as portable JSON, or embedded in an exported Three.js factory. Editing preserves discovered beacons and the scout's reachable position; undo returns a scout stranded on vanished terrain to a surviving tile. Switching presets invalidates in-flight image decodes to avoid stale selections.

The scout uses a deterministic binary-heap A* route planner over visible cells,
replacing a linear scan of every frontier tile. The compass finds the minimum-cost
reachable uncollected beacon with **one** slope-aware Dijkstra traversal instead
of repeating a separate A* search for every beacon. Equal-cost targets still
choose the lower tile ID; paths remain four-connected and never cross invisible
tiles. Randomized tests compare route costs against independent Dijkstra and
the compass against separate A* searches. CPU timing receipts cover 28×28 and
64×64 synthetic grids and must not be described as measured GPU frame-time or
image-to-3D fidelity improvement.

The scout only follows connected nontransparent cells. The **Find next beacon** compass uses the same slope-aware A* cost as the scout to choose the closest reachable *uncollected* target; it never teleports or fabricates a path through transparent water. If all remaining treasure is disconnected, use the bridge tool and try again. Pixel brightness is only an artistic height proxy, not measured elevation. Directly tapping a beacon also collects it. Animated hopping stops under reduced-motion preferences. Image files over 12 MB or decoded images over 36 megapixels are refused.

## Ideas for later

Wire the numeric relief into an opt-in v2.2 scene-to-world workflow after the scene schema and measurement gates exist. For now it is a standalone, downstream proof of concept, not a new gate or feature inside the core generator.
