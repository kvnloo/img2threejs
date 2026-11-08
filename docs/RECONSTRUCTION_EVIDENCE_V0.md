# Reconstruction Evidence v0

Status: downstream experiment only

## Question

Can externally produced image evidence improve img2threejs reconstruction quality, or reach the same quality with fewer render/search evaluations, without making that evidence authoritative?

## Input contract

Optional CLI surface:

```
--evidence-bundle path/to/reconstruction-evidence/manifest.json
```

The manifest points to local relative artifacts only.

Supported v0 roles:

- `reference`
- `depth`
- `foreground-mask`
- `material-mask`
- optional `normal`
- optional `edge`
- optional `alternate-view`

Each artifact records:

- semantic role
- relative path
- width / height
- SHA-256
- provenance
- state: `measured | inferred | generated`
- optional confidence/status

Generated evidence must never be represented as observation.

## Authority boundary

External evidence may:

- prioritize search coordinates;
- add candidate-scoring terms;
- establish bounded ordinal constraints;
- improve crop / region ownership.

External evidence may not:

- silently rewrite authored geometry;
- silently rewrite PBR scalars;
- mark a sculpt/review pass complete;
- bypass hard gates;
- manufacture confidence when an artifact is absent or malformed.

Absent evidence must preserve current behavior.

## First integration

Keep the builder and existing evaluator fixed.

### Foreground mask

Use only to improve silhouette ownership/scoring.

### Depth

Convert to ordinal relations between already-identified parts. Do not treat monocular depth as metric geometry.

### Material masks

Use only to improve region ownership. Do not infer finish class from the mask itself.

Multiview geometry synthesis is explicitly out of scope for v0.

## Decision receipt

Any fitting decision influenced by external evidence should be able to report:

```json
{
  "evidence": [
    {
      "role": "depth",
      "artifact": "depth.png",
      "sha256": "...",
      "effect": "candidate-score",
      "reason": "part-a-before-part-b"
    }
  ]
}
```

## A/B

Same reference set, starting spec, render budget, and evaluator:

- A: current reference-only pipeline
- B: reference + evidence bundle

Measure:

- silhouette IoU
- landmark reprojection error
- ordinal depth violations
- material-region agreement
- evaluations consumed
- wall-clock time
- hard-gate pass/fail

Train/tuning references and holdout references remain separate.

## Relationship to Dreamloop RSI

PR #15 tests better allocation of a fixed search budget from replay history.

This experiment tests a richer observation surface.

Run independently first, then a 2×2:

| | replay off | replay on |
|---|---:|---:|
| evidence off | baseline | replay |
| evidence on | evidence | evidence + replay |

## Promotion boundary

Do not upstream ComfyUI coupling.

If the experiment wins, the upstreamable surface is a backend-neutral evidence manifest plus one local fixture and deterministic adapter tests.
