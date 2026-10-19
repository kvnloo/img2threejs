# Real-render experiment: Dreamloop-RSI silhouette recovery A/B

## Goal

Produce the first **real render + real Divine Eye** evidence for the downstream Dreamloop-RSI RFC.

This sits between the synthetic replay benchmark and public-photo reconstruction: references are actual Three.js renders from known procedural target specs, so correct mesh parameters are known and image ambiguity does not confound the exploration-policy experiment.

## Hypothesis

At the same render/evaluator budget, a coordinate order learned from prior realized root-neighborhood worlds reaches higher clean silhouette IoU (or the same target with fewer renders) than current fixed index order.

## Experimental targets

Use at least three geometry families:

1. box / assembled hard-surface proportions;
2. cylinder or lathe-like axial form;
3. tapered-sweep or another nontrivial profile.

For each family:

- author a target spec/vector;
- generate and render the target once as the immutable reference;
- create several perturbed starting vectors;
- keep camera, lighting, renderer and Divine Eye version fixed.

No private images.

## Research branch

`rfc/dreamloop-rsi-mesh-fidelity`

Use:

- `root_neighborhood.py` to evaluate every ± coordinate from the same baseline;
- `learn_coordinate_priority()` on training worlds;
- downstream `FitConfig.coordinate_order` prototype to deploy fixed vs learned orders.

The render callback must use the actual img2threejs -> Three.js path, not a fake numeric objective.

## Current native-fitter preflight (not an accepted holdout A/B)

The `real_render_smoke.py score` step now calls the actual downstream
`fit_against_divine_eye` for **both coordinate orders** on the same captured
Chromium candidate set. Each order receives three native Divine Eye calls:
root + both signed probes on its first coordinate. It refuses unrendered
candidates and checks that every re-evaluated score/hard-gate receipt agrees
with the original native image evaluation.

It writes `worlds/paired-real-fitter.json` containing visited PNG hashes,
candidate order, fit history, clean IoU for actually visited candidates,
and explicit `liveRenderBudgetClaim: false` / `holdoutClaim: false` markers.
This is stronger than replaying numbers through the policy simulator: the
production fitter and hard-gate adapter are genuinely exercised on real
WebGL screenshots. **However**, screenshots are all captured *ahead of time*,
so only evaluator invocations, not on-demand browser renders, are budgeted.
The same procedural root is used for both orders, without policy learning.

This does not satisfy the acceptance bar below. Fresh, independent
multi-family holdouts and truly bounded live-render calls remain required.

## Immutable original and separate calibration cohort

The original `(0.78, 0.76)` root and ±0.14 neighborhoods are retained verbatim:
the native fitter's 3-evaluation visits were all `low-confidence/probe`,
with **no accepted clean score**. We do not reinterpret their raw
silhouette IoU as accepted optimization progress.

An explicitly tagged **calibrated preflight** uses root `(0.90, 0.94)`,
first-coordinate ±0.10 and second-coordinate ±0.06 against the same
original procedural target. It was chosen *after inspecting the original
probe-only outcome*, for the sole purpose of exercising an accepted
quality route without changing Divine Eye's 0.85 target or hard gates.
This is **calibration data, not a blinded independent holdout**.

GitHub Actions runs both cohorts in separate jobs/artifacts using
`real_render_smoke.py prepare DIR --neighborhood original|calibrated`.
Each score step revalidates the committed cohort vectors, image hashes
and native evaluator calls. No live-render timing claim or policy learning
is made for either cohort.

## Split

Minimum initial run:

- 12 training worlds: 4 per geometry family;
- 6 replay-validation worlds: 2 per family;
- 6 fresh holdout worlds: 2 per family.

Fresh holdout must not influence learned order.

## Budgets

Run paired comparisons at:

- small: 3 evaluations;
- medium: 5 evaluations;
- larger: enough to expose convergence behavior.

Count the root evaluation identically.

## Metrics

Primary:

- best **clean** `signals.silhouetteIoU` at equal budget.

Secondary:

- clean target-IoU success rate;
- evaluations-to-target;
- `scaleDelta`;
- `aspectRatioDelta`;
- hard-gate failure rate;
- render/evaluator wall time.

A higher raw IoU with a hard gate cannot win.

## ABAB order

Alternate holdout execution order:

- world 1: fixed then learned;
- world 2: learned then fixed;
- repeat.

## Acceptance

Move to public-photo demos only if:

- learned policy improves holdout median best clean IoU by >= 0.01 at a constrained budget, **or**
- matches within 0.002 while reducing median evaluations-to-target by >= 20%;
- no increase in scale/aspect hard-gate failures;
- larger-budget behavior converges rather than showing a fabricated permanent advantage;
- all artifacts, hashes and failed runs are retained.

## Outputs

Write under:

`experiments/dream_rsi_mesh_fidelity/runs/real-render-v0/`

Required:

- `config.json`
- target specs + hashes
- perturbed starting vectors
- `worlds/*.json`
- fixed + learned policy artifacts
- per-candidate renders / Divine Eye JSON
- `usage.json`
- `results.json`
- `REPORT.md`

## Promotion gate

Only after this passes:

1. repeat on public real-photo references;
2. fresh ABAB holdout;
3. consider promoting only the tiny priority-order primitive in upstream issue #162.

Do not promote the replay engine/world store/policy learner upstream from this experiment.
