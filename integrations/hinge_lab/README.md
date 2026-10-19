# Hinge Lab (experimental, offline)

This is an isolated visual companion to the code-only procedural Three.js
factory proposed for [img2threejs/img2threejs#118](https://github.com/img2threejs/img2threejs/issues/118),
originally reported by [mariusargint](https://github.com/mariusargint).
It is not automatic image reconstruction or a production collision gate.

## Use the offline artifact

Download the **hinge-lab-offline** artifact from the
[Hinge Real Photo A/B research workflow](../../.github/workflows/hinge-reference-photo.yml),
extract it, and open index.html with a browser supporting WebGL2.

The package contains index.html, bundled Three.js and generated model code in
bundle.js, a credited reference.jpg, a provenance manifest.json, and four
browser-tested screenshots.

There is no CDN, account, live network, remote model loading or backend. The
build fetches the licensed reference photo, then bundles it locally.

Use the four fold sliders to rotate the emitted scene's real hinge joints.
**Flatten all** resets to zero, and **Photo pose** applies a manually authored
reference-like pose. Drag or touch the canvas to orbit the model.

Enable **Collision experiment** to inject a small red BoxGeometry obstacle
at the selected panel's positive 90-degree location. Evaluate the sweep to
receive one of three states:

- collision: penetration was found during the supported rigid-box sweep.
- certified-clear: all tested intervals have conservative separation proofs
  under the static-obstacle/rigid-transform assumptions.
- unresolved: the checker cannot prove clearance at the available resolution.
  This is not a safe verdict.

The checker is not a universal mesh collision solver or physical sheet
simulator. Obstacles are research-only injections and were not recovered
from the photograph. The **Export pose JSON** control saves angles and the
most recent collision verdict locally; no external service is contacted.

## Build and acceptance

The workflow runs the offline builder under Node 22 and Python 3.10 with
pinned Three.js r180, TypeScript, esbuild and Playwright installed.

Example environment variables:

    HINGE_REFERENCE_PHOTO=/path/to/box.agr.jpg
    HINGE_LAB_OUTPUT=/tmp/hinge-lab-offline

Command:

    node integrations/hinge_lab/build_and_test.mjs

The builder executes the actual procedural Python generator; typechecks
its emitted TypeScript; makes an IIFE JavaScript bundle with all local
dependencies; and runs Playwright directly against the file URL.

The end-to-end test covers four panels, photo preset, flat reset, hinge
collision and reverse sweep, selected-panel behavior, downloaded JSON,
mobile horizontal overflow, actual WebGL rendering and zero network calls.
Failing assertions stop CI; screenshots are retained as evidence.

## Photo credit and scientific limits

Photo: **Box.agr.jpg** by **Arnold Reinhold**, Wikimedia Commons,
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
[Source and attribution](https://commons.wikimedia.org/wiki/File:Box.agr.jpg).
The artifact's manifest includes the exact photo SHA-256 and license URL.

Geometry, camera and fold angles were manually authored. Source photo
dimensions and material textures were not reconstructed automatically.
[HINGE_EVIDENCE_STUDY.md](../../docs/HINGE_EVIDENCE_STUDY.md) reports
the mixed image comparisons and restrictions of the experimental sweep.

Maintainer proposal: [img2threejs/img2threejs#169](https://github.com/img2threejs/img2threejs/issues/169).
Keep this independent downstream until the maintainers accept the hinge contract.
