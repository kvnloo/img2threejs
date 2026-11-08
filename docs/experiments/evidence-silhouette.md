# Experimental evidence silhouette penalty

`fit_against_divine_eye` remains receipt-only by default. The keyword-only
`experimental_silhouette_weight=0.0` preserves the existing objective and JSON
output. A positive weight explicitly enables **one** experimental term:

```python
result = fit_against_divine_eye(
    initial, bounds, render_for_parameters, reference_png,
    config=frozen_config,
    evidence_manifest=manifest_path,
    experimental_silhouette_weight=0.05,
)
```

The weight must be finite in `[0, 0.1]`. This is a bounded lab mechanism, not a
recommended calibrated weight or an automatic image-to-3D system.

## Contract

- A positive weight requires a validated bundle and caller reference bytes whose
  SHA-256 matches its reference artifact. The declared white-is-one foreground
  mask is decoded directly; all connected components are retained.
- Reference red-channel values and rendered alpha values are thresholded at
  `>= 128` on a fixed `224 x 224` nearest-floor sampling grid. No crop, alignment,
  registration search, largest-component selection or photograph-mask estimator
  is applied. Camera/framing must be fixed by the caller.
- The render must be an 8-bit non-interlaced PNG with matching dimensions and a
  nonempty, non-whole-frame alpha silhouette. RGB-only/fully opaque images fail
  closed rather than guessing a foreground. Degenerate reference masks fail too.
- Already-approved candidates use `raw_fidelity - weight * (1 - silhouette_iou)`.
  Rejected and probe candidates retain objective `-1`. No verdict or hard failure
  is cleared; the original raw fidelity and correction history remain available.
- `fitEvidenceSilhouette` records IoU, penalty, objective, mask identity, threshold,
  grid, extraction rule and coverage. It is absent at weight zero. The existing
  `fitEvidenceBundle` remains provenance only. Depth and material masks receive
  no scoring or geometry/material authority in either mode.

## Evaluation limits

Establish real receipt-only parity before experimenting. Freeze the initial
parameters, bounds, camera, renderer, seed, evaluator and budget; render and
score both arms independently. Report raw fidelity, original hard failures,
IoU, objective, chosen parameters, evaluation count and wall time separately.
An all-rejected plateau is not visual success or an improvement. A positive
result on a tuning reference is not generalization; use an untouched independent
holdout before claiming improvement. A generated public reference is not measured
or synthetic metric ground truth.

The core remains standard-library-only. Renderer adapters are external callers;
this change does not add a browser dependency or a universal renderer API.


## Actual-browser synthetic-control gate

An isolated GitHub Actions job now runs the experimental scoring path on
**actual Chromium + Three.js WebGL pixels**. It creates an original procedural
reference and two *fixed-camera* candidate scenes: an identical one and a
deliberately displaced one. These are tests of the evaluator and integration,
**not** user-photo reconstruction, photogrammetry, or DA3 inference.

The run:

1. Saves the real 224×224 RGBA WebGL canvases (no mocked screenshots).
2. Re-encodes the renderer's reference to an RGB8 PNG plus a white-is-one
   foreground-mask PNG, with content hashes and `state=generated`.
   The required U16 depth artifact is explicitly a *synthetic gradient*
   and never contributes a score or claims metric depth.
3. Validates the full evidence manifest and checks that silhouette IoU is
   near 1.0 for the identical scene, lower for the deliberately displaced one.
4. Compares no-evidence and receipt-only fitting via the existing shadow
   parity gate after JSON serialization, with equal evaluation ceilings.
5. Executes the positive-weight experimental arm against the same **real**
   browser images, checking selection changes but raw evaluator fidelity
   and hard-gate authority remain untouched.
6. Uploads PNGs, hashes, generated manifest and a machine-readable report.

On 2026-10-19 the first successful controlled run reported **IoU 1.000**
for the matching scene and **0.479** for the displaced scene, with **three
evaluations per arm** and exact receipt-only parity:
[run and artifacts](https://github.com/kvnloo/img2threejs/actions/runs/39270168672).
The evaluator score in the candidate-ranking fixture is fixed by design;
these IoU values are measured from actual WebGL pixels, but **not evidence
of improved photo reconstruction accuracy**.

To reproduce (all browser dependencies remain isolated from the core):

```bash
mkdir -p /tmp/img2-evidence-browser-deps
cd /tmp/img2-evidence-browser-deps
npm init -y
npm install --no-save playwright@1.56.0 three@0.169.0
npx playwright install chromium
cd /path/to/kvnloo/img2threejs
IMG2THREEJS_BROWSER_DEPS=/tmp/img2-evidence-browser-deps \
  node integrations/reconstruction_evidence/browser_silhouette_smoke.mjs
```

**Next gate:** replace the generated reference with a rights-cleared real
photograph and a verified DA3 evidence bundle from
[`kvnloo/ComfyUI#5`](https://github.com/kvnloo/ComfyUI/pull/5);
record exact bundle hashes, reuse the identical model/evaluator/render budget
for both arms, check hard-gate parity, then repeat on an untouched holdout.
Do not promote this experimental silhouette objective or claim gains before
that independent evidence exists.
