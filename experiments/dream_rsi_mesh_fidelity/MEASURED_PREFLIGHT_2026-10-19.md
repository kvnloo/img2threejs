# Measured native fitter preflight — 2026-10-19

This is a **measured, controlled procedural** Chromium/Three.js + native Divine Eye
experiment. It is **not** an image-to-3D reconstruction result, a learned-policy
win, an independently blinded holdout, or an equal-budget *live browser-render*
experiment.

## Provenance

- Exact source commit: `11b03975989b296c4e84cc80a6d2c16988cdc28e`.
- Frozen spec fixture: `forge/tests/fixtures/reference_target_conformance_spec.json`
  SHA-256 `d9aed0f517f9fcad13a661edb6dd1ab82f0ab50bcce4795b0c373ca5ab827bb0`.
- [Green two-cohort Chromium workflow](https://github.com/kvnloo/img2threejs/actions/runs/39282007847).
- [Original cohort raw PNG/spec/Divine Eye/fit artifacts](https://github.com/kvnloo/img2threejs/actions/runs/39282007847/artifacts/12201500964).
- [Post-hoc calibrated cohort artifacts](https://github.com/kvnloo/img2threejs/actions/runs/39282007847/artifacts/12201131232).
- [Exact-head Python + Node CI](https://github.com/kvnloo/img2threejs/actions/runs/39282008525).
- Both arms use the **same pre-rendered** candidate images, and each order
  actually re-invokes the native Divine Eye evaluator exactly three times.
  The reference is a browser render of the known target, not a photograph.

## Measurements

All silhouette figures below come from independent native Divine Eye
`signals.silhouetteIoU` measurements of Chromium PNG files. `Best clean`
is recorded **only** for fitter-accepted results; `probe/low-confidence`
outputs do **not** count as successful optimization.

| Cohort | Root (x, z) | Three-evaluation coordinate order | Visited candidates | Best clean silhouette IoU | Best accepted fidelity |
| --- | --- | --- | --- | ---: | ---: |
| Original | (0.78, 0.76) | Fixed (0, 1) | root, c0−, c0+ | none | none |
| Original | (0.78, 0.76) | Reverse (1, 0) | root, c1−, c1+ | none | none |
| Post-hoc calibrated | (0.90, 0.94) | Fixed (0, 1) | root, c0−, c0+ | **0.9892** | 0.9516 |
| Post-hoc calibrated | (0.90, 0.94) | Reverse (1, 0) | root, c1−, c1+ | **0.9786** | 0.9418 |

- Target self-comparison: silhouette IoU **1.0000**, fidelity **1.0000**.
- Original cohort: root native fidelity `0.7935`, x+ `0.8297`,
  z+ `0.8280`; all below the unchanged `0.85` acceptance threshold.
  Largest visited raw IoUs were `0.9430` and `0.9384`, respectively,
  but they were **not approved results**.
- Calibrated cohort: root `0.9680` IoU (fidelity `0.9073`),
  x+ `0.9892` (fidelity `0.9516`), z+ `0.9786`
  (fidelity `0.9418`). Both arms produced accepted improvements.
- The calibrated fixed order beat reverse order by **0.0106 silhouette IoU**
  at the same **3 evaluator calls**. This does **not** demonstrate a benefit
  from learned priority ordering; fixed order happened to win on this one
  post-hoc-selected neighborhood.
- `hardGateFailures` was empty in the recorded six image variants per
  cohort, but accept/reject was still governed by the native fidelity
  threshold. Hard-gate parity by itself is not a visual quality win.

## Interpretation / next required experiment

The production fitter and browser/evaluator plumbing now support genuine
`continue`-eligible outputs without relaxing any quality gate.
**The hypothesized learned-order improvement remains unproven.**
For an upstream-ready claim, use the existing protocol in
`REAL_RENDER_EXPERIMENT.md`: at least 12 training worlds, 6 replay-validation
worlds, 6 fresh holdouts spanning three geometry families, with an
ABAB-controlled order and equally bounded **on-demand** browser renders.
Never use the calibrated cohort as a holdout or optimize its initial values
after seeing its scores.

Provenance must accompany any later comparisons: commit, reference/spec
SHA-256, camera, renderer revision, recorded PNG SHA-256, full native Divine
Eye score + verdict, hard gates, actual render/evaluation count and order.
Do not convert a `probe` candidate's raw IoU into a clean best score.
