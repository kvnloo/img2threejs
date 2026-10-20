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

## Adaptive conservative interval check

The optional [test-only checker](../forge/tests/hinge_sweep_collision.mjs)
`certifyFoldSweep()` improves on fixed 5-degree samples. It returns exactly
one of three states:

- `collision`: a tested pose intersects the static obstacle.
- `certified-clear`: every inspected angle interval has a conservative
  separation certificate.
- `unresolved`: available angular resolution or the evaluation budget
  cannot prove the interval clear. **Unresolved is not a pass.**

For a rigid box and a fixed obstacle, the maximum radial distance `R` of
any box vertex to the hinge axis is bounded by the perpendicular distance of
the box center to the axis, plus each oriented half-extent projected onto
the plane perpendicular to that axis:

```text
R <= |perpendicular(center - hingeOrigin)|
     + sum(halfExtent[i] * sqrt(1 - dot(boxAxis[i], hingeAxis)^2))

maximum vertex displacement from an interval midpoint
    <= R * abs(intervalEnd - intervalStart) / 2   [radians]

if SAT midpoint separation gap > displacementBound + epsilon:
    certify this interval clear
else:
    check the two half intervals, up to a bounded depth/check budget
```

The second inequality uses arc length to overestimate chord displacement.
It remains conservative regardless of the direction of the moving face.
The along-hinge-axis length of a box does **not** increase the sweep radius.
The algorithm checks endpoints and middle angles, restores the authored
hinge angle, and never treats insufficient resolution as a safe verdict.

[Continuous interval research CI](https://github.com/kvnloo/img2threejs/actions/workflows/hinge-reference-photo.yml)
includes adversarial controls: a narrow collision precisely at 2.5 degrees
which endpoint-only 0/5-degree sampling misses, a clear sweep, an unresolved
shallow-budget case, and a long box oriented along the hinge axis.

**Domain restrictions:** box geometry only; static obstacle external to
the hinge subtree; no skinned deformation; no sheared/nonuniformly scaled
hinge-parent world frame; one rotating joint at a time. Numerical tolerances
and ray/mesh physics beyond the supported box case are outside the
certificate. Full arbitrary-mesh continuous collision detection remains
unsolved, and the study's existing photographic IoU result is unchanged.

## Generated factory + deterministic stress evidence

An additional [browser run](https://github.com/kvnloo/img2threejs/actions/runs/39277454315)
uses the **actual emitted TypeScript carton factory**, rather than
the stand-alone manual collision hierarchy:

- All **four generated box flaps** (`back-flap`, `front-flap`,
  `left-flap`, `right-flap`) were tested with an independent small
  obstacle placed at their +90° world-space centers. This covers axes in
  both X and Z directions.
- Each had clear rest/end poses, a recorded mid-sweep collision at +90°,
  `collision` on the positive sweep, and `certified-clear` on the reverse
  sweep under the rigid static-obstacle assumptions.
- The same browser run typechecks generated Three.js code, renders the
  actual generated flap against a temporary red obstacle, and includes
  `generated-sweep-collision.png` and all per-flap verdicts in
  `measurements.json`. The obstacle is a *test injection*; it is not
  inferred from the source photograph.

A [second regression run](https://github.com/kvnloo/img2threejs/actions/runs/39277065926)
includes **14 passing Node tests**, with a deterministic pseudorandom
falsification exercise. In **48** seeded rigid-box configurations compared
against an independent 0.5° sampled reference sweep, **41** had observed
collisions, **6** were conservatively certified clear, and **1** was
unresolved. **No certified-clear case contained a collision observed by the
dense samples.** The seed is `0x5eeda11c`; the tests assert all statuses,
witnesses, and restoration of authored angles.

This is useful regression coverage, **not a statistical or formal
completeness guarantee** for arbitrary geometry, animations, moving
obstacles, or numerical tolerances. Dense sampling can miss very short
collisions too. A safety-critical consumer must still treat unsupported
shapes and unresolved intervals as unsupported/unknown.

## Equal-budget deterministic camera framing

The first photo comparison used an uncalibrated fixed orthographic camera,
so two different pivot schemes were measured at an arbitrary common
pan/zoom. The camera itself was an important confounder.

A follow-up [headless Chromium camera-fitting experiment](https://github.com/kvnloo/img2threejs/actions/runs/39371859530)
holds **all geometry, fold angles, lighting and segmentation constant**
within each model. A deterministic coordinate descent varies **only**
the orthographic image-plane pan (dx/dy) and zoom, using the same search
steps and bounds for each model. No AI, model downloads, photogrammetry
or feature/texture reconstruction are involved.

| Same photo / fixed-frame IoU | Unfitted | Fitted | Held-out tiles |
| --- | ---: | ---: | ---: |
| Correct parent-local hinges | 0.602342 | **0.886611** | **0.885300** |
| Center-pivot counterfactual | 0.611218 | 0.824392 | 0.823011 |

Both fits used **25 unique evaluations** (budget ceiling **37**) of the
same four-stage, three-axis coordinate-descent algorithm. Parameters:
hinged `(dx=-0.06, dy=+0.30, zoom=1.27)`; center-pivot
`(dx=-0.06, dy=+0.24, zoom=1.21)`.

To guard against a trivial per-pixel fitting artifact, only alternating
24-pixel checkerboard tiles from the *same image* contribute to the
optimization objective. Complementary tiles report the held-out score;
neither score is used to change geometry. **These tiles are spatially
correlated and are not an independent validation scene.** Camera fitting
on the same original photograph necessarily risks overfitting; results
must not be described as general reference-fidelity improvement.

The sensitivity test also reruns the fixed-camera IoU calculation on
**nine locked warm-segmentation thresholds** around the original
(red-minus-green in `{8,13,18}` and red-minus-blue in `{15,22,29}`).
It does **not** refit the camera for each threshold. The resulting
[sensitivity CI](https://github.com/kvnloo/img2threejs/actions/runs/39372800831)
passes eight camera/segmentation unit tests plus the existing 14 rigid
collision tests. Across this small threshold grid, hinged IoU ranges
**0.886144–0.886611** and center-pivot IoU ranges
**0.822808–0.824392**; the local fitted ordering is unchanged in
all nine cases. This is evidence of **limited segmentation stability
on the same one image**, not broader scene robustness.

The better hinge IoU after equal registration is useful evidence that
pivot choice matters *for this manually authored example*, alongside
the exact seam-continuity and collision tests. It does not prove
automatic image-to-3D reconstruction quality or photoreal likeness.
The experiment does not search camera rotation, perspective,
reference landmarks, mesh shape, fold angles, scene lighting or color
thresholds. The repository already provides a separate landmark
correspondence camera solver under `forge/stage1_intake/`; this study
does **not** replace or duplicate that contract.

The isolated [Hinge Lab](../integrations/hinge_lab/README.md) also has
a clearly labeled, optional **Photo-framed view** using the measured
hinged-camera pan/zoom preset; desktop/mobile presentation can vary
with viewport aspect and with its intentionally different lighting.
Interactive screenshots are *not* additional quantitative matches.

## Independent hierarchy-transform property oracle

A new [actual-generated TypeScript/Three.js property harness](https://github.com/kvnloo/img2threejs/actions/runs/39375272367)
adds **five** procedural hinges: two nested cardboard creases, one arbitrary
3D diagonal, an axis directed **opposite Three.js +Y**, and a nested
diagonal hinge with signed nonzero rest angle. The fixture is emitted by
the real generator, typechecked with TypeScript, bundled and executed in
Chromium rather than approximated by handwritten mesh code.

Against an independent parent-frame rotate-about-line equation, a
fixed-seed `0x118a517` sweep evaluates **192 cases** (64 per ancestor
transform across three frames: identity, nonuniform scale, X reflection).
Every case tests five hinges and three distinct child-local points.
The browser accepted **2,880 world-position assertions** plus **960
on-axis invariant assertions**, **3,840 checks in total**.
The authored child-node local positions are also checked for drift and
all test transforms are restored before screenshot rendering.

This guards negative/reversed hinge directions, nested parent frames,
arbitrary axes, mesh-node rotations, nonuniform and reflected ancestors,
and explicit `restAngleDeg` initialization. It does **not** establish
photographic fidelity, deformation, contact, or collision freedom. The
standalone, reference-facing carton comparison remains a separate test.

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
