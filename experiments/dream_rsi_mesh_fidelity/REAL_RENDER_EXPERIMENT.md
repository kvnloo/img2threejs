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
