# Pocket World (experimental)

A small, playful image-to-Three.js experiment: bring a picture, explore a colorful 28 × 28 voxel relief, send a glowing scout along deterministic A* paths, collect five beacons, change the lighting, then **export a standalone code-only `THREE.Group` factory**. Three hand-coded procedural color postcards work without uploading a reference.

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
```

An optional DOM-interaction smoke test runs in headless Chromium with a mocked Three.js runtime (requires `python3` with `playwright` and `Pillow` installed):

```sh
python3 integrations/pocket_world/tests/dom_smoke.py
```

It covers real browser image decoding, async upload race handling, pointer controls, scout movement, and downloadable exports. **It does not verify WebGL rendering or Three.js import-map/CDN loading.**

Node 18+ works for the pure-data tests. Browser interaction requires modern WebGL and import-map support; mobile tap/drag/pinch are supported. Images are center-cropped and downsampled to 28 × 28 RGBA cells. This limits detail and intentionally avoids claims of true 3D reconstruction.

The scout only follows connected nontransparent cells. Its slope-aware A* planner uses pixel brightness, not measured terrain elevation. Transparent gaps may be unreachable; directly tapping a beacon still collects it. Animated hopping stops under reduced-motion preferences. Image files over 12 MB or decoded images over 36 megapixels are refused.

## Ideas for later

Wire the numeric relief into an opt-in v2.2 scene-to-world workflow after the scene schema and measurement gates exist. For now it is a standalone, downstream proof of concept, not a new gate or feature inside the core generator.
