# Hinge reconstruction evidence — 2026-10-19

**Status:** downstream research, not an upstream implementation PR or a fidelity claim.

The original edge-hinge request is [img2threejs/img2threejs#118](https://github.com/img2threejs/img2threejs/issues/118),
reported by [mariusargint](https://github.com/mariusargint).
The canonical implementation is [downstream PR #37](https://github.com/kvnloo/img2threejs/pull/37);
upstream [contribution intent #169](https://github.com/img2threejs/img2threejs/issues/169) awaits maintainers.

## Reproducible reference study

Source: [Box.agr.jpg](https://commons.wikimedia.org/wiki/File:Box.agr.jpg),
**Arnold Reinhold**, Wikimedia Commons, [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
The reference is a single photograph, not a recovered 3D mesh.

The Python [fixture](../forge/tests/emit_hinge_photo_fixture.py) authors a five-panel
procedural box. The [Three.js runner](../forge/tests/hinge_photo_ab.mjs)
compares two implementations of *those same authored panels* under fixed
projection, materials, lighting, and manually specified fold angles:
off-center edge pivots versus the incorrect center-pivot counterfactual.

Both output masks use a fixed warm-cardboard/gray-background color rule.
Two **different** IoU measures are reported; they must not be conflated:

| Metric | Center pivot | Edge hinge | Edge − center |
| --- | ---: | ---: | ---: |
| Independently bbox-normalized 256² silhouette IoU | 0.815287 | 0.843857 | +0.028570 |
| Registered fixed-frame 960×760 silhouette IoU | 0.611218 | 0.602342 | **−0.008876** |
| Maximum measured hinge-to-floor seam gap (model units) | 0.311634 | 5.77e-16 | −0.311634 |

**Interpretation:** correct pivots strongly preserve authored seam contact, and
the normalized silhouette improves for this fixture, but fixed-frame IoU
*favors the center-pivot baseline*. The evidence is mixed. No claim is made
that the hinge implementation reconstructs photographs more faithfully in
general. Independent box normalization removes positioning/scale evidence;
the fixed-frame metric retains those errors but still relies on manual camera
and coarse color segmentation.

- Reference SHA-256: `385f42408d114bad1cfc06adf773a64b1902779c9a4515da07413fbac0a13530`
- [Measured CI run, JSON, side-by-side screenshot](https://github.com/kvnloo/img2threejs/actions/runs/39269793640)
- Reconstruction bounds: one 2D image, no automatic model fitting, no
  photogrammetric camera calibration, no texture reconstruction, no claim to
  recover corrugation, wall thickness, or real-world dimensions.

## Swept-intersection negative control

The [research OBB detector](../forge/tests/hinge_sweep_collision.mjs) uses
the 15 separating-axis tests for rigid, non-sheared `THREE.BoxGeometry`
volumes. [Five Node tests](../forge/tests/test_hinge_sweep_collision.mjs)
establish both correctness and that intermediate motion is checked rather
than simply inspecting the start and end poses.

One constructed test rotates a panel around its edge past a separate
obstacle. Sweeping 0° → +180° and sampling every 5°:

- Start/end: both **collision-free**.
- First sampled penetration: **70°**, overlap **0.002795** model units.
- Positive sweep: **9** penetrating samples.
- Same endpoint via 0° → −180°: **0** penetrating samples.

The discriminator correctly detects the harmful sign despite identical
endpoint geometry. This does **not** establish continuous-time collision
avoidance (5° sampling may miss transient contact), topology-wide
self-intersection, arbitrary primitive support, deformable sheets, or
collision-free motion of the photographed carton. This is a *test-only
negative control*, not a production physics feature.

## Reproduce and review

```sh
# Branch: study/hinge-real-photo-ab-20261019
npm install --no-save --no-package-lock --ignore-scripts \
  three@0.180.0 @types/three@0.180.0 \
  typescript@5.9.3 esbuild@0.25.12 playwright@1.56.1
npx --no-install playwright install --with-deps chromium
node --test forge/tests/test_hinge_sweep_collision.mjs

# See .github/workflows/hinge-reference-photo.yml for the reproducible
# reference download, provenance and headless browser invocation.
```

**Upstream gate:** the maintainer must decide whether a schema-level hinge
is appropriate before a pull request is offered. Keep the implementation
small, author credit intact, and do not add these optional research
dependencies to the core Python pipeline.
