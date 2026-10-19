# img2threejs — canonical downstream promotion queue

- Audit: 2026-10-18
- Origin: https://github.com/img2threejs/img2threejs
- Coordination fork: https://github.com/kvnloo/img2threejs
- Dedupe key: `promotion-queue:img2threejs/img2threejs`
- Queue location: this file (fork Issues disabled, HTTP 410). No fallback issue in oss-factory.
- Goal lock: increase verified, maintainer-accepted code-only Three.js reconstruction fixes without duplicate PRs or invented fidelity measurements.
- Source attribution: preserve original issue reporters, PR authors, and existing contributors through linked original source threads.
- Origin permission: read-only via this connector; no new origin writes approved by this queue.

## Ready for human review

- **READY_FOR_HUMAN_REVIEW** — [#10 path containment](https://github.com/kvnloo/img2threejs/pull/10), head `bdd1e1dd55210c465158ad9b9fbccc4d3f371c0d`, Python CI [36879633940](https://github.com/kvnloo/img2threejs/actions/runs/36879633940) green. Reported security requirement: origin [#103](https://github.com/img2threejs/img2threejs/issues/103). **Origin publication still blocked** on maintainer intent triage, nonduplicate PR scope and explicit human approval.
- **READY_FOR_HUMAN_REVIEW** — [#9 stop review](https://github.com/kvnloo/img2threejs/pull/9), head `ec85cac46a24b4cfad42b40b22076f05a3642838`, Python CI [36879530001](https://github.com/kvnloo/img2threejs/actions/runs/36879530001) green. Reproduction and expected CLI stopped behavior: origin [#92](https://github.com/img2threejs/img2threejs/issues/92). **Origin publication still blocked** by the same policy gate.

## Existing upstream review (highest priority)

- **ORIGIN_LIVE / BLOCKED_EXTERNAL** — https://github.com/img2threejs/img2threejs/pull/149
  - Base-owned post-rig plugin gate re-sweep for https://github.com/img2threejs/img2threejs/issues/125; contribution intent https://github.com/img2threejs/img2threejs/issues/148.
  - Head `686a3bb11f4ed8b5ba078d13c2aadb407b6f3591`, open draft and mergeable (2026-10-18).
  - Workflow runs 36337675371 / 36337783054 reported `action_required`, zero native test jobs. No maintainer review/comments observed. Do not describe as CI-green. Need maintainer approval of fork workflow, full Python suite and `test_run_gates.py` on the exact head; review before marking ready.
  - Next: retain existing PR; no duplicate, no unsolicited maintainer ping.

## Needs proof: downstream fixes (ordered)

| State | PR and checked head | Source issue / intent | Smallest next action |
| --- | --- | --- | --- |
| CHECK P0 | [#10 region-path containment](https://github.com/kvnloo/img2threejs/pull/10) `bdd1e1dd55210c465158ad9b9fbccc4d3f371c0d` | [#103](https://github.com/img2threejs/img2threejs/issues/103) / [#151](https://github.com/img2threejs/img2threejs/issues/151) | Run traversal fixture + full material tests; verify ordinary IDs and paths. Shared file dependency: do before #12/#13 |
| CHECK P0 | [#9 stop-review transition](https://github.com/kvnloo/img2threejs/pull/9) `ec85cac46a24b4cfad42b40b22076f05a3642838` | [#92](https://github.com/img2threejs/img2threejs/issues/92) / [#152](https://github.com/img2threejs/img2threejs/issues/152) | Run stale cursor, repeat-read, and `next.py` exit-code tests with full workflow suite |
| CHECK P1 | [#11 completed-pass ledger](https://github.com/kvnloo/img2threejs/pull/11) `a3c9bbf40387b5ffe70e75c6b423dc0fd1bf9208` | [#119](https://github.com/img2threejs/img2threejs/issues/119) / [#153](https://github.com/img2threejs/img2threejs/issues/153) | Resolve backwards-compatibility: current patch promotes mismatch from warning to normal-validation error. Consider strict-quality classification with normal validation still warning. Test both; current-head CI [39200578418](https://github.com/kvnloo/img2threejs/actions/runs/39200578418) green |
| CHECK P1 | [#12 interior-material crops](https://github.com/kvnloo/img2threejs/pull/12) `09679a4947cd0b6d2d2b93dbba162af836776169` | [#136](https://github.com/img2threejs/img2threejs/issues/136) / [#159](https://github.com/img2threejs/img2threejs/issues/159) | Review automatic `interior_crop=True` on every manifest bbox. Opt-in `interiorCrop:true` now required; mixed-background and invalid-flag regression cases added. Policy, Node 18/22, and full Python CI [39201493165](https://github.com/kvnloo/img2threejs/actions/runs/39201493165) **green** at exact head; still needs real crop comparison and maintainer triage |
| CHECK P1 | [#13 texture-family safety](https://github.com/kvnloo/img2threejs/pull/13) `c4f6c88e317397081215ffd98df82a147abd4027` | [#137](https://github.com/img2threejs/img2threejs/issues/137) / [#160](https://github.com/img2threejs/img2threejs/issues/160) | Unknown/incompatible families must not silently overwrite authored PBR; test mixed material taxonomy |
| CHECK P2 | [#14 low-albedo matte relief](https://github.com/kvnloo/img2threejs/pull/14) `4a127625f8769c37a68ed0b1fdaf39b41a7294d5` | [#120](https://github.com/img2threejs/img2threejs/issues/120) / [#161](https://github.com/img2threejs/img2threejs/issues/161) | Verify reference-relative/noise-floor criterion and representative render evidence |

All six downstream PRs are open and non-draft but **not proven ready** here. Their associated intent issues still await maintainer triage. No extra origin PR before authorization, dedupe, and native evidence. The fork default `main` matched upstream `main` on 2026-10-18; recheck before any cherry-pick.

## Held: real-render evidence required

- **LIMITED** [#16 reconstruction-evidence contract](https://github.com/kvnloo/img2threejs/pull/16) head `d505e1b52203d9422fc63021dcec3ae05eed83f1`. Existing tests are synthetic/provenance. Next: genuine depth/mask producer bundle, exact reference-byte hashes, receipt-only shadow-parity and browser render traces. Scoring term only after identical-budget measured comparison. Companion work: https://github.com/kvnloo/ComfyUI/pull/5.
- **LIMITED** [#15 Dreamloop replay](https://github.com/kvnloo/img2threejs/pull/15) head `1969a2f5e13e8bb2865607dd7bb9227c659534a3`. Synthetic 30/30 holdout supports a search-order mechanism, **not** fidelity gain. Next: fixed-render-budget genuine WebGL/Divine Eye holdout and ABAB. Origin proposal: https://github.com/img2threejs/img2threejs/issues/162.

## Held / superseded

- Downstream PRs #1–#8 were closed 2026-10-17. Treat their original commits as attribution/evidence; don't recreate validation drafts.
- Existing origin contribution-intent duplicates exist for #92, #103, #119 and #137. Do not submit more; avoid unsolicited contact while triage is pending.
- Repo mandates Python stdlib core, backward compatible object specs, no binary/mesh download, and render-vs-reference evidence for visual changes.

## Landed
- No new origin merge of this fork's work verified in this wave.

## Throughput rubric
Prioritize `reviewer feedback -> current required CI -> integration/rebase -> full runtime fidelity -> newly scoped work`.
A promotion receipt must include the exact head SHA; RED/GREEN before/after and full `python3 -m unittest discover -s forge/tests -p 'test_*.py'`; `IMG2THREEJS_SHOWCASE_ROOT` TypeScript check where relevant; real render/comparison when fidelity changes; maintainer triage/authorization; no origin PR duplication.
Output: origin-merged commits and verified blockers cleared, not PR or issue volume.

## Wave receipt: 2026-10-19 UTC

- **Implementation repair:** Updated the *existing* [downstream PR #12](https://github.com/kvnloo/img2threejs/pull/12), head `09679a4947cd0b6d2d2b93dbba162af836776169`. Material analysis no longer blindly chooses interior masking for every bbox; explicit verified `interiorCrop:true` opt-in with type check, provenance and two negative tests.
- **Verification:** PR issue policy workflow 39201493173 success; CI workflow 39201493165 npm Node 18/22 jobs success, Python CI **in progress** at last read. Do not claim full green or visual evidence. No end-to-end WebGL capture was run here.
- **External status:** Existing origin PR #149 remains draft/action_required. No origin write performed in this wave. Fork issues were disabled (410); queue remains on this repository branch rather than a factory fallback issue.

## CI reconciliation: 2026-10-19 UTC

Exact heads rechecked for #9–#16. **All eight current heads have successful Python CI workflows**. PR #11's former failure was from its superseded head `bd5a9e435b37a2fcd2218caf8ac91f97bcf34d1d`; new head `a3c9bbf40387b5ffe70e75c6b423dc0fd1bf9208` passed Python/npm/policy. PR #12's repaired head `09679a4947cd0b6d2d2b93dbba162af836776169` likewise passed full Python/npm/policy. Experimental #15/#16 remain **LIMITED** despite green CI because no genuine render-fidelity measurements have been established.

Best near-term lever: surface existing green candidates #10 then #9 through appropriate human/maintainer triage, resolve material CI-independent fidelity evidence, keep #149 in its existing upstream thread; stop duplicate intent or speculative PR creation.

## Factory registration

Pending [factory registry draft PR #197](https://github.com/kvnloo/oss-factory/pull/197) adds this project to the canonical 38-project registry. This is **not merged** and creates neither a new automation nor origin write authority; until review, this fork document remains the durable project queue.
