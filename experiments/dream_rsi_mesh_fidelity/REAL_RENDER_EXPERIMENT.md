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

## Completed two-cohort preflight and measured outcome (2026-10-19)

The exact-source `11b03975989b` Chromium matrix finished with **both cohorts
successfully scored**, not merely rendered. See
[the numeric report and linked, inspectable artifacts](MEASURED_PREFLIGHT_2026-10-19.md).

The original cohort had **no accepted candidate in either arm**. The
post-hoc calibration produced clean accepted scores; at three evaluator calls
the existing fixed order reached **0.9892** clean silhouette IoU versus
**0.9786** for reverse order. This is not evidence that a learned ordering
helps. The calibration is neither an independent holdout nor an on-demand
render-budget experiment, so **no upstream fitter-promotion gate is passed**.

## New: on-demand browser render budget A/B

`live_budget_ab.py --out DIR` now runs **after** the conventional six-image
preflight. For each of the two coordinate orders, the native
`fit_against_divine_eye` callback invokes the **actual Chrome executable**
through `real_browser_capture.mjs --variant NAME --tag UNIQUE_TAG` for
each requested candidate. Every call recompiles the candidate's
generated TypeScript, opens a new headless Chromium instance, renders a
new 256px PNG and stores an independent WebGL2 readiness/error receipt.

- Exactly **3 freshly rendered candidates per order** (root + signed probes
  on the prioritized coordinate); the same pre-existing target image is
  supplied as the reference and excluded equally from both policy budgets.
- The callback refuses any unseen vector, out-of-budget request, reused
  screenshot filename, altered source spec or malformed browser receipt.
- New PNG hashes, actual browser invocation count, elapsed seconds,
  native Divine Eye verdict, fidelity, silhouette IoU and hard-gate failures
  are published at `worlds/live-browser-budget-ab.json`. Partial work is
  retained if a later capture fails. Evaluations and browser renders are
  counted separately, and unexpected dispatch order is an error.
- The original and calibrated cohorts are independent CI matrix jobs with
  all their candidate PNGs and source hashes retained.

This **does** exercise an on-demand browser cost boundary, unlike the earlier
pre-rendered fitting preflight. It is still only a single procedural geometry
family and a post-hoc calibration cohort, not a trained policy, genuine
unseen holdout, public-photograph test, reproducible cross-hardware latency
benchmark or evidence for an upstream advantage.

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

## Preregistered multi-family v2 study (after isolating true primitive silhouettes)

A first [v1 registration](MULTIFAMILY_V1_REGISTERED.json) was run as
an exploratory three-family pilot. **Visual inspection found that the
inherited equipment-case lid remained macro geometry across all scenes**,
dominating the frame even for the lathe/tapered-sweep roots. The affected
v1 image/evaluator outcomes cannot establish a clean multi-family result:
they are retained for provenance and **excluded** from subsequent
training, validation and holdout.

The corrected, separate
[`MULTIFAMILY_V2_REGISTERED.json`](MULTIFAMILY_V2_REGISTERED.json)
was committed **before the first v2 browser render**. It preserves the
same 24 world IDs, train/validation/holdout division and thresholds,
but demotes the old lid from blockout-macro to later-stage geometry.
The native generator is tested to emit *exactly the isolated root*
in each family. Different registration byte hashes prevent inadvertent
mixing of v1 and v2 receipts. It specifies 12 training worlds (four
per family), six validation worlds (two per family) and six reserved
holdouts (two per family).

The three **different native Three.js geometry constructors**, not simply
new labels for the case model, are:

- `assembled-box`: beveled/tapered hard-surface box;
- `lathe`: variable-radius axial vessel/shoulder/waist;
- `tapered-sweep`: a bent four-station ellipse with changing cross-section.

Every variant is authored as an ObjectSculptSpec derived from the *public,
hash-checked* canonical source fixture; the project's actual
`generate_threejs_factory.py --pass-id blockout` emits the TypeScript.
The same headless Chromium WebGL2 capture and native Divine Eye scorer
measure every candidate. Varying profile indices make the authored shape
differ between individual worlds within a family. No source photographs
or imported meshes are used.

### Split isolation

The scripts
[`registered_multifamily.py`](registered_multifamily.py),
[`registered_policy.py`](registered_policy.py),
[`registered_holdout_ab.py`](registered_holdout_ab.py) and
[`aggregate_holdout.py`](aggregate_holdout.py) enforce this sequence:

1. **Register** exact world IDs, source spec SHA, root/target vectors,
   step sizes, reference renderer, budgets and acceptance thresholds.
2. **Train** only on all 12 training-world **approved** native outcomes.
   A probe/low-confidence IoU cannot become training success.
3. **Validate** on the six separate worlds. Validation only vetoes an
   already learned order on median quality, hard gates or per-family
   degradation. It cannot retrain the order.
4. **Freeze** a canonical SHA-256 policy receipt naming exactly 12
   training and six validation source-receipt hashes.
5. **Unlock holdout only** if validation approved a non-identity order,
   the receipt SHA and registration match and there are no prior
   holdout outcomes. Six worlds are run ABAB in alternating fixed/frozen
   order. Each arm calls Chromium **three fresh times** from the native
   fitter; reference cost is accounted separately but identically.
6. **Aggregate** all six worlds with no dropped failures, recording null
   scores as non-accepted instead of silently selecting easier cases.
   A negative finding remains a successful scientific execution, *not*
   a fabricated learning victory.

The workflows are
[`rsi-multifamily-browser.yml`](../../.github/workflows/rsi-multifamily-browser.yml)
(three-family pilot) and
[`rsi-multifamily-full.yml`](../../.github/workflows/rsi-multifamily-full.yml)
(18 training/validation captures, frozen policy, optional six-world
holdout). The full study limits capture concurrency to six jobs.

**Acceptance is unchanged**: median best *approved* silhouette IoU on
holdout improves by at least 0.01, or quality matches within 0.002 with
at least 20% fewer paired target-reaching evaluations, without increased
hard-gate failures or a per-family regression. Every study artifact
contains model/spec hashes, PNGs and unmodified native verdicts. Budget 5
and larger convergence studies, human independent blindness, and public
source-photo A/B remain future work.

This is **split-isolated but publicly registered**: a reader can inspect
holdout parameters in the committed file. We therefore do not advertise
this as cryptographically secret or human-blinded. The earlier calibrated
case and all v1 lid-confounded scenes are excluded from every v2 training,
validation and holdout world. None of these procedures changes
upstream core thresholds or justifies an upstream PR before human triage.

### Reproduce the registration and pilot

```bash
python3 experiments/dream_rsi_mesh_fidelity/registered_multifamily.py register
python3 -m unittest -v \
  forge.tests.test_rsi_multifamily_protocol \
  forge.tests.test_rsi_policy_freeze \
  forge.tests.test_rsi_registered_holdout

OUT=/tmp/rsi-box-train-01
python3 experiments/dream_rsi_mesh_fidelity/registered_multifamily.py \
  prepare --world-id assembled-box-train-01 --out "$OUT"
# Install the browser dependencies in an isolated experiment environment first.
CHROME_BIN="$(command -v google-chrome || command -v chromium)" \
  node experiments/dream_rsi_mesh_fidelity/real_browser_capture.mjs "$OUT"
python3 experiments/dream_rsi_mesh_fidelity/registered_multifamily.py \
  score --out "$OUT"
```

## Promotion gate

Only after this passes:

1. repeat on public real-photo references;
2. fresh ABAB holdout;
3. consider promoting only the tiny priority-order primitive in upstream issue #162.

Do not promote the replay engine/world store/policy learner upstream from this experiment.
