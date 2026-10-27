# Synthetic replay benchmark

This is a **mechanism test only**. It is not evidence that real img2threejs meshes improve yet.

Date: 2026-10-01

## Setup

- 30 deterministic synthetic training worlds.
- 30 untouched deterministic synthetic holdout worlds.
- Four coordinates with different underlying expected silhouette-IoU gains.
- Each root exposes both lower/upper moves for every coordinate.
- One coordinate occasionally produces a hard-gated candidate.
- Fixed control policy: coordinate order `(0, 1, 2, 3)`.
- Candidate: order learned from training root neighborhoods.
- Target clean IoU: `0.75`.
- Same replay budget for control and candidate.

The learner uses the **best clean direction per coordinate per comparable parent**, then averages those gains across worlds. It does not average a good `+` move with the intentionally bad `-` move, and by default it does not let historically deeper branches receive extra votes.

## Result

Learned order: `(2, 3, 1, 0)`.

| Budget | Fixed mean best IoU | Learned mean best IoU | Delta | Fixed success | Learned success |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 0.6763 | 0.7743 | **+0.0981** | 0% | **100%** |
| 5 | 0.6965 | 0.7743 | **+0.0778** | 0% | **100%** |
| 7 | 0.7743 | 0.7743 | 0.0000 | 100% | 100% |
| 9 | 0.7743 | 0.7743 | 0.0000 | 100% | 100% |

## Interpretation

The experiment demonstrates the intended mechanism:

- history changes **where a limited evaluation budget is spent**;
- the learned policy wins only while budget is constrained;
- once the fixed policy has enough budget to evaluate all important coordinates, both policies converge;
- hard-gated candidates remain in history but cannot become the best clean result.

That shape is desirable. The goal is not to manufacture a permanent score advantage after exhaustive search; it is to reach the same or better clean mesh fidelity with fewer expensive render/evaluator calls.

## What this does not prove

- no real Three.js mesh was rendered;
- no Divine Eye image evaluation ran;
- synthetic gain structure was intentionally learnable;
- this does not satisfy the upstream evidence gate in issue #162.

Next required evidence is a real `fit_against_divine_eye()` trace adapter plus complete first-step neighborhoods on public/demo reference subjects.
