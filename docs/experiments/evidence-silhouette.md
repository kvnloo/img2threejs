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
