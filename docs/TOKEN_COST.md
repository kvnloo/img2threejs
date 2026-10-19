# Token Cost Analysis

The numbers below are engineering estimates, not a measured benchmark. They are order-of-magnitude figures anchored to one reference build (a rounded-bevel loot chest: gradient enamel, gold corner brackets, an emissive emblem, resolved in about six render-review cycles). Actual cost varies with the model tier, image resolution, object complexity, and — above all — how many review cycles a subject needs. Treat them as a cost model, not a guarantee.

A measured benchmark, based on empirical data across real reconstructions, is planned for v1.5. See [ROADMAP.md](../ROADMAP.md) for details.

## Where the tokens go per full object reconstruction

| Stage | Est. model tokens | Notes |
|---|---|---|
| Deterministic scripts (probe, assessment, spec, validate, generate, sync) | ~2k-5k total | Run as subprocesses. This is the work that is near-free. |
| Read the reference image | <1k | A small reference; higher-res costs more. |
| Author assessment + detail inventory + spec JSON | ~15k-25k | The spec is the largest text artifact. |
| Write and edit the Three.js factory | ~20k-45k | Scales with part count and edit iterations. |
| Render-review loop (5-8 cycles) | ~30k-70k | The dominant cost; scales linearly with cycles. |
| **Total, one object** | **~80k-180k** | Simple/few-cycles to complex/many-cycles. |

## One render-review cycle in isolation

| Step | Est. model tokens |
|---|---|
| Capture screenshot (browser tool) | ~0 (tool call) |
| Package comparison sheet (stdlib script) | ~0 (subprocess) |
| Inspect the comparison sheet with vision | ~2k-3k |
| Write the review and scores (script) | ~1k-2k |
| **Per cycle** | **~5k-12k** |

## Character reconstruction cost

Characters cost more (more review cycles plus landmark and projection checks): roughly ~150k-350k for a full stylized or likeness-maximized reconstruction with the v1.2 character generator.

## What this buys you

- Deterministic scripts contribute close to zero model tokens, so validation, gating, detail counting, sheet packaging, and pipeline state never eat context.
- Model tokens are spent only on vision (reading one sheet per pass), authoring the spec, and writing code.
- The gates are the savings mechanism: strict-quality blocks codegen on an underspecified spec, and the detail-inventory gate blocks it on missing detail — each avoided bad render saves roughly one full cycle (~10k-20k tokens).
- The single biggest lever on cost is the review-cycle count. A well-formed spec up front is worth more tokens than any micro-optimization downstream.

## Measured benchmark: provider receipts required

All figures above remain **estimates**. The new opt-in script aggregates actual
provider usage records; it does not invoke an agent or reconstruct an object.
No measured corpus or measured savings is claimed yet.

Capture one JSONL event per provider request, using a unique event ID for each
render-review attempt. Omit prompts and image bytes from the usage log:

```json
{"run_id":"demo-a","event_id":"call-001","stage":"assessment","model":"your-model","provider":"your-provider","usage_source":"provider","usage":{"prompt_tokens":1000,"completion_tokens":300,"total_tokens":1300},"cost_usd":"0.0123"}
```

To claim a **complete reconstruction**, each run needs measured calls for
`assessment`, `spec`, `codegen`, and `render-review`. Stage labels may
include additional measurements. Counts must come from actual provider usage.
If the provider supplies tokens but no price, omit `cost_usd` rather than
assuming free service.

```bash
python3 scripts/benchmark_token_cost.py work/usage.jsonl \
  --minimum-runs 3 --out work/usage-report.json
```

The deterministic report breaks down calls, prompt/completion/total tokens
and known (possibly partial) billed USD by stage. Comparable A/B benchmarks
must hold reference set, model, render budgets, and stage routing fixed,
and should preserve engine/agent revisions separately with the run artifacts.
