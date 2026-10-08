# RFC: Dreamloop-RSI for Recursive Mesh-Fidelity Improvement

Status: downstream research RFC  
Scope: `kvnloo/img2threejs` experimentation first; only bounded primitives graduate upstream  
Primary target: mesh silhouette/proportion fidelity under a fixed render-evaluation budget  
Non-goals: model-weight training, self-modifying core code, gate bypasses, or replacing the code-only Three.js artifact

## 1. Summary

`img2threejs` already has most of the inner recursive-improvement loop:

1. author a parameterized procedural model;
2. render it;
3. compare it against the reference with deterministic gates / Divine Eye;
4. revise parameters or code;
5. stop under bounded correction rules.

What it does not learn is **how to explore that correction space**. `forge/stage4_review/fit_params.py` uses one fixed coordinate order and one fixed branching pattern. The correction loop uses fixed routing and stopping heuristics. Every run therefore pays again for exploration lessons previous runs already discovered.

Dream-RSI's useful idea here is deliberately narrower than “let the agent rewrite itself”:

> Treat completed reconstruction search histories as exact replay simulators over branches that were actually evaluated, improve a small exploration policy offline against those histories, then redeploy only a policy that beats the incumbent under a no-regression gate.

The builder, Three.js emitter, evaluator, fidelity thresholds, security policy, and approvals stay fixed. Only the exploration policy changes.

```text
reference/spec
    |
    v
ONLINE DISCOVERY
policy pi_t -> choose mesh parameter/operator branches
            -> build/render/evaluate
            -> record immutable discovery tree T_t
    |
    v
REPLAY WORLD POOL
H_t = {T_1 ... T_t}
    |
    v
DREAM
candidate policies replay realized branches only
with zero new render/evaluator execution
    |
    v
NO-REGRESSION SELECT
incumbent is always a candidate
    |
    v
FRESH HOLDOUT
paired online A/B at equal budget
    |
    v
REDEPLOY pi_(t+1)
```

The initial upstreamable slice is much smaller than this RFC: **priority-ordered bounded fitting**. Downstream Dreamloop-RSI learns which mesh-fit coordinate should be evaluated first; upstream would only expose a deterministic coordinate-priority primitive after real evidence shows better mesh fidelity at the same evaluation budget.

## 2. Why this fits img2threejs

Dream-RSI assumes a fixed discovery agent and evaluator while the exploration policy changes. img2threejs already has that separation:

- fixed procedural generator / render callback;
- fixed Divine Eye / Tier-1 metrics;
- fixed hard gates such as silhouette, scale and aspect ratio;
- bounded analysis-by-synthesis fitting in `fit_params.py`;
- bounded stop logic in `correction_loop.py`;
- provenance-rich evaluator records.

The current fitter evaluates coordinates in index order and tests lower then upper moves. That is harmless when evaluation is cheap and the budget is large. It matters when each evaluation means regenerating geometry, rendering views, reading pixels, and running gates.

A fixed order can spend a small budget on low-yield dimensions before reaching the parameter controlling the visible defect. Historical runs can tell us which dimensions/operators tend to produce clean fidelity gain.

## 3. Design principles

### Fixed evaluator; evolving exploration

The following are frozen within an experiment lineage:

- reference artifact/hash;
- base spec/hash;
- render/capture configuration;
- Divine Eye/Tier-1 metric versions;
- hard-gate thresholds;
- code-only output contract;
- evaluation budget accounting;
- holdout subjects.

A policy may choose *where to spend evaluations*. It may not redefine success.

### History is exact only where history went

A discovery tree is an exact simulator for realized branches only. If replay selects an existing edge, its stored outcome is exact. If it selects an unobserved branch, replay returns **out-of-support**. It must never interpolate, predict, synthesize, or borrow a nearby score.

### Incumbent is always in the candidate set

```text
candidate_set = [incumbent, revision_1, ..., revision_M]
selected = argmax(replay_score(candidate_set))
```

A tie keeps the incumbent.

### Fixed-budget comparisons

“Better” means better under the same budget:

- best clean silhouette IoU after B evaluations;
- success rate at a fixed clean target IoU;
- evaluations to target;
- hard-gate failure rate;
- render/evaluator cost.

### Hard gates stay authoritative

A higher raw IoU with a scale/aspect hard failure cannot beat a clean candidate.

### Improve policy artifacts, not core code

Allowed policy choices may include:

- coordinate priority;
- direction priority;
- branch width;
- step-size schedule;
- retry/backtrack;
- component/view priority;
- stop/continue;
- budget allocation.

Policies may never weaken gates, broaden permissions, alter credentials, or mutate evaluator code.

## 4. Inner and outer loops

### Inner loop: mesh improvement

```text
parameters/spec
  -> procedural mesh
  -> canonical render(s)
  -> Divine Eye / structural metrics
  -> correction
  -> repeat or stop
```

The first experiment restricts the target to **silhouette/proportion fidelity**, using existing `silhouetteIoU`, `scaleDelta`, `aspectRatioDelta`, and gate-approved fidelity.

### Outer loop: exploration-policy improvement

1. Deploy incumbent policy online.
2. Record complete attempt tree and costs.
3. Freeze the tree into a replay world.
4. Append it to the world pool.
5. Generate candidate policy revisions.
6. Replay each revision over the frozen pool.
7. Keep the incumbent unless another candidate strictly improves the objective.
8. Run a fresh paired holdout.
9. Deploy only after holdout/no-regression passes.

No model is required for the first policy revisions. We first prove the loop with deterministic coordinate-order policies. Model-written policies are a later experiment.

## 5. Discovery tree schema

A world represents one governed reconstruction/fitting episode.

```json
{
  "schemaVersion": 1,
  "worldId": "...",
  "subjectId": "...",
  "referenceHash": "sha256:...",
  "baseSpecHash": "sha256:...",
  "metricVersion": "divine-eye/...",
  "parameterSchema": [
    {"index": 0, "name": "body.width", "bounds": [0.7, 1.3]},
    {"index": 1, "name": "body.height", "bounds": [0.7, 1.3]}
  ],
  "rootId": "n0",
  "nodes": []
}
```

Each evaluated node stores immutable evidence:

```json
{
  "id": "n17",
  "parentId": "n4",
  "action": {
    "kind": "coordinate-step",
    "coordinate": 1,
    "direction": -1,
    "step": 0.125
  },
  "parameters": [1.0, 0.875],
  "artifact": {
    "specHash": "...",
    "factoryHash": "...",
    "renderHash": "..."
  },
  "evaluation": {
    "silhouetteIoU": 0.883,
    "scaleDelta": 0.041,
    "aspectRatioDelta": 0.028,
    "rawFidelity": 0.87,
    "hardGateFailures": [],
    "verdict": "pass"
  },
  "cost": {
    "renderEvaluations": 1,
    "wallMs": 0,
    "modelCalls": 0
  }
}
```

Required invariants:

- unique node IDs;
- exactly one root;
- every non-root parent exists;
- immutable hashes after freeze;
- metric version recorded;
- finite metrics only;
- rejected/errored attempts remain;
- “not measured” is explicit, never zero;
- replay cannot reveal a child result before selecting/paying for it.

## 6. Replay simulator

At replay start the root outcome is revealed. The frontier contains only recorded children of visited nodes that fit the remaining budget.

A policy receives:

- visited outcomes;
- metadata of currently available actions;
- spent and remaining budget.

It does **not** receive a frontier node's score before choosing it.

```text
observation = reveal(visited)
action = policy.choose(observation)

if action not in recorded_frontier:
    out-of-support
else:
    reveal recorded outcome
    charge cost
    update frontier
```

Initial replay output:

- best clean IoU;
- best node ID;
- evaluations to target;
- spent budget;
- visited IDs.

## 7. Policy v0: coordinate priority

The first policy is deliberately small and inspectable:

```python
coordinate_order = (3, 0, 2, 1)
direction_order = (-1, +1)
```

When several recorded branches are available, lower coordinate rank wins, then direction rank, then stable node ID.

Learn it from history by aggregating clean parent->child gain:

```text
gain = child.silhouetteIoU - parent.silhouetteIoU
```

Sort semantic coordinates by mean gain across training worlds.

This is not the final RSI policy. It is the smallest proof that history can improve allocation of expensive render evaluations.

## 8. Promotion objective

Frozen-world selection is lexicographic:

1. clean target-IoU success rate;
2. mean best clean silhouette IoU at budget B;
3. lower evaluations-to-target;
4. lower total evaluation cost.

A tie retains the incumbent.

Replay cannot prove generalization, so final promotion requires fresh online holdout.

Initial real-world promotion bar:

- at least 10 governed holdout fits across >=3 shape families;
- identical references, cameras, bounds, and max evaluations for incumbent/candidate;
- candidate improves median best clean silhouette IoU by >=0.01 absolute **or** matches within 0.002 while reducing median evaluations-to-target by >=20%;
- zero increase in scale/aspect hard-gate failure rate;
- no previously passing subject becomes unrecoverably worse at equal budget.

These are experiment gates, not permanent product constants.

## 9. Experiment ladder

### E0 — baseline capture

Record current `fit_against_divine_eye()` evaluations as a tree. Replay of the incumbent must reproduce the online winner.

### E1 — exact replay

Synthetic worlds prove:

- no future leakage;
- out-of-support rejection;
- fixed budget accounting;
- hard-gated high-IoU candidates cannot win;
- ties keep incumbent;
- deterministic reports.

Initial prototype: 7 tests passing.

### E2 — coordinate priority

Collect complete +/- first-step neighborhoods from real fits. Learn ordering from training worlds. Compare against fixed index order at small budgets.

### E3 — contextual coordinate priority

Condition priority on observed defects:

- scale failure -> size coordinates first;
- aspect mismatch -> width/height/taper;
- clean macro silhouette + local mismatch -> component-local dimensions;
- repeated no-gain -> reduce step or change operator.

### E4 — branch width

Let policy decide how many sibling candidates to evaluate before committing.

### E5 — stopping

Replay candidate stop policies while preserving the existing hard ceiling.

### E6 — multi-view worst-first allocation

Allocate evaluation budget to the current worst canonical view. No averaging may hide a failed view.

### E7 — component-local policy

Once object-ID/component footprints exist, decision unit becomes `(view, component)`. Regenerate one named part instead of the whole object.

### E8 — operator policy

Expand actions to taper, bevel, lathe controls, sweep controls, subdivision, tier promotion/demotion, and local module regeneration.

### E9 — model-written policy revisions

Only after replay/auditing is trustworthy, permit an LLM to propose a policy artifact in a closed schema/AST language. It never modifies generator/evaluator code.

### E10 — full outer cycles

Repeat online -> freeze -> dream -> holdout -> deploy, and track whether the Pareto frontier improves across unseen subjects.

## 10. ABAB experiment discipline

For real renders:

```text
A = incumbent
B = candidate

subject 1: A then B
subject 2: B then A
subject 3: A then B
subject 4: B then A
```

Record exact ref/spec hashes, policy hash, renderer/version, metric version, order, render count, evaluator count, best clean IoU, hard gates, and stop reason.

Do not silently replace failed runs. Failed experiments remain useful world data.

## 11. Data splits

- **Training pool**: policy improvement.
- **Replay validation pool**: frozen worlds withheld from policy proposal generation.
- **Fresh holdout**: real builds/renders never replayed during policy development before promotion.
- **Canary**: small live deployment with rollback; only frozen validated runs join training history.

## 12. Relationship to existing code

### `fit_params.py`

Seed for the first slice. Keep bounded evaluation and gate-aware objective. Downstream wraps it first.

### `divine_eye.py`

Fixed evaluator. Thresholds/weights are frozen during a policy experiment.

### `correction_loop.py`

Hard ceiling remains authoritative. Policies may stop earlier, not silently extend the ceiling.

### `derive_geometry.py`

Future semantic parameter source. RSI becomes more useful when coordinates have stable meanings such as `body.width` rather than anonymous indices.

### TRELLIS research direction

`docs/RESEARCH_TRELLIS2_TO_IMG2THREEJS.md` proposes dense measurement, semantic emission, per-component correction, and analysis-by-synthesis fitting. Dreamloop-RSI learns how to allocate search efficiently over those richer operators. It does not replace that direction.

## 13. Small upstream vertical slice

Do **not** upstream the world store, replay engine, policy editor, or recursive outer loop yet.

The first upstream candidate should be a tiny product-neutral primitive:

### Priority-ordered bounded fitting

Conceptual API:

```python
FitConfig(
    ...,
    coordinate_order=(2, 0, 1),
)
```

Rules:

- omitted -> exact current behavior;
- value must be a permutation of every coordinate index;
- same lower/upper semantics;
- same max iterations/evaluations;
- same hard-gate handling;
- order serialized in provenance;
- malformed orders fail loud.

Why this boundary:

- useful without Dream-RSI;
- deterministic and testable;
- lets callers use sensitivity/domain knowledge;
- downstream RSI can learn the order without upstream depending on RSI;
- provides a direct A/B: better clean silhouette IoU at the same render budget.

Before promotion we require:

1. unit fixture where two orders under the same evaluation cap produce different best objective values;
2. real downstream A/B showing replay-learned order improves clean IoU or reduces renders to target;
3. default-order compatibility;
4. no hard-gate regressions.

## 14. Cost model

Track separately:

- online model calls;
- policy-development model calls;
- mesh generation/build calls;
- render captures;
- evaluator calls;
- replay evaluations;
- wall time;
- GPU time where available.

Do not claim logical batching is a wall-clock speedup without measurement.

Primary efficiency metric:

```text
clean silhouette IoU gained per render evaluation
```

Secondary:

```text
renders to target clean IoU
```

## 15. Failure modes

### Replay support bias
Candidate looks good because incumbent explored branches it likes.  
Defense: explicit out-of-support + fresh holdout.

### Evaluator overfitting
Policy learns Divine Eye quirks instead of mesh fidelity.  
Defense: frozen evaluator, multiple signals/hard gates, holdout visual audit.

### Policy churn
Equivalent policies rotate.  
Defense: strict improvement; ties keep incumbent.

### Tree explosion
Complete branching is expensive.  
Defense: bounded branch width; partial worlds are valid; later policy learns where branching pays.

### Stale worlds after metric changes
Defense: metric/evaluator version in world identity.

### Untrusted model policy
Defense: postpone; closed language, no I/O/network/tools, bounded compute, replay before deployment.

## 16. Implementation phases

### Phase A — replay kernel (now)
Downstream-only exact-support replay, fixed budget, hard-gate-aware winner, coordinate policy, gain learner, no-regression selection.

### Phase B — trace adapter
Convert `fit_against_divine_eye()` evidence into world records. Add explicit parent/action metadata if current provenance is insufficient.

### Phase C — complete root neighborhoods
For public/demo subjects evaluate all +/- first-step coordinate branches.

### Phase D — learned policy
Learn coordinate ordering and pass replay no-regression.

### Phase E — fresh ABAB holdout
Run candidate/incumbent at equal budgets.

### Phase F — upstream primitive
Only after E proves value, propose the tiny coordinate-order feature in `fit_params.py`.

### Phase G — richer policies
Branch width, stop policy, view/component routing, operators.

## 17. Experiment ledger

```text
experiments/dream_rsi_mesh_fidelity/runs/<run-id>/
  config.json
  refs.json
  worlds/*.json
  policies/*.json
  replay/*.json
  holdout/*.json
  usage.json
  results.json
  REPORT.md
```

Every report records hypothesis, control, candidate, frozen metric versions, budget, data split, results, regressions/disagreements, verdict, and next experiment.

## 18. First 12 experiments

1. Synthetic exact replay / no future leakage.
2. Hard-gated high-IoU exclusion.
3. Coordinate-gain learner on synthetic worlds.
4. Fixed-budget learned-order win on synthetic holdout.
5. Adapter round-trip from current fitter trace.
6. One public/demo object with complete root neighborhood.
7. Same object at small/medium/full render budgets.
8. Three shape families with leave-one-family-out ordering.
9. Defect-conditioned order.
10. Multi-view worst-view allocation.
11. Component-local search after object-ID footprint exists.
12. Fresh ABAB holdout incumbent vs selected policy.

Only experiment 12 can trigger upstream promotion.

## 19. Program success

Success is not one perfect reconstruction. The Pareto frontier should move across cycles:

- higher clean mesh fidelity for the same compute;
- same fidelity with fewer renders/model calls;
- fewer repeated failed directions;
- more localized corrections;
- no weakening of gates or editability.

## 20. Relationship to Dream-RSI

This is an independent domain adaptation, not a reproduction of the unreleased full system.

Preserved ideas:

- explicit programmable exploration policy;
- history as exact replay over realized discovery branches;
- cheap offline policy evaluation;
- incumbent-in-candidate-set no-regression selection;
- redeployment that creates new worlds and expands the simulator pool.

Domain additions:

- img2threejs visual/geometry hard gates;
- named procedural parts;
- render-budget accounting;
- eventual `(view, component, feature)` correction granularity.

References:

- Dream-RSI project: https://dream-rsi.com/
- Dream-RSI repo: https://github.com/zhengkid/Dream-RSI
- `forge/stage4_review/fit_params.py`
- `forge/stage4_review/correction_loop.py`
- `docs/RESEARCH_TRELLIS2_TO_IMG2THREEJS.md`
