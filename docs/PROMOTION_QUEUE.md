# img2threejs — canonical downstream promotion queue

## Current verified wave — 2026-10-19 (supersedes older entries below)

**Goal:** maximize upstream acceptance, native correctness, and measurable Three.js reconstruction fidelity without duplicate contribution-intent issues or speculative PRs. Origin `img2threejs/img2threejs`; fork `kvnloo/img2threejs`. Fork Issues disabled (410), so this project-local document is the canonical queue, not an oss-factory fallback issue.

### Existing upstream PR — action required by maintainer

- **ORIGIN_LIVE / BLOCKED_EXTERNAL:** [upstream #149](https://github.com/img2threejs/img2threejs/pull/149), current exact head `4c69704ddb8d66b52a0990f6c02ee16d05a600d3`, code changes limited to intended four files and current origin `main`. [Fork verification PR #22](https://github.com/kvnloo/img2threejs/pull/22) / [native CI #39202797533](https://github.com/kvnloo/img2threejs/actions/runs/39202797533) passed full Python and npm Node 18/22. Existing origin PR description updated with these results. **Origin Actions still `action_required` due maintainer approval requirement.** No reviewer feedback. Remains draft. No second upstream PR.

### Ready for human promotion review — maintainer triage still pending

- **READY_FOR_HUMAN_REVIEW / NOT ORIGIN_PUBLISHED:** [fork #10](https://github.com/kvnloo/img2threejs/pull/10) at `fd80986fe4e0ac033752ff631d6fb36711ad2216`, [CI #39203172523](https://github.com/kvnloo/img2threejs/actions/runs/39203172523) full Python/npm/policy green. Fixes unsafe filename derivation, long names and collisions, preserving authored semantic ID. Origin [bug #103](https://github.com/img2threejs/img2threejs/issues/103) reported by truongsontung; existing contribution intents [#151](https://github.com/img2threejs/img2threejs/issues/151), [#157](https://github.com/img2threejs/img2threejs/issues/157). **One shared implementation only; wait for maintainer claim**.
- **READY_FOR_HUMAN_REVIEW / NOT ORIGIN_PUBLISHED:** [fork #9](https://github.com/kvnloo/img2threejs/pull/9) at `9e212d593ebcfc978ecac901a5f71d5d554bd715`, [CI #39202669384](https://github.com/kvnloo/img2threejs/actions/runs/39202669384) full Python/npm/policy green. Non-destructively merged current origin main, covers stale reviewCursor and deliberate out-of-sequence stop exclusions. Origin [bug #92](https://github.com/img2threejs/img2threejs/issues/92) reported by ludekvodicka; contribution intents [#152](https://github.com/img2threejs/img2threejs/issues/152), [#156](https://github.com/img2threejs/img2threejs/issues/156). **Wait for maintainer claim**.

The user's explicit approval of a bounded promotion wave is recorded in the existing fork PRs #9/#10. It does **not** replace upstream contributor claim/triage or grant a default-branch merge.

### Real-runtime evidence — not learned-model acceptance

- **MEASURED PRELIMINARY / HOLD from origin:** [fork draft #15](https://github.com/kvnloo/img2threejs/pull/15), exact `4fd34463bbcf6d874d08f0753a4c4d7e4193b5ed`, [native WebGL2/Divine Eye CI #39204567096](https://github.com/kvnloo/img2threejs/actions/runs/39204567096) **passed**; [Python/npm CI #39204567758](https://github.com/kvnloo/img2threejs/actions/runs/39204567758) **passed**. [Screenshots, source hashes, evaluator JSON and replay-world artifact](https://github.com/kvnloo/img2threejs/actions/runs/39204567096/artifacts/12164804152). One fixed procedural equipment-case scene, browser rendered with real generated Three.js and scored by native Divine Eye: target 1.0000, root .9179, c0− .8953, c0+ .9430, c1− .8995, c1+ .9384 silhouette IoU. Immutable observed-score replay world with two budget-three policies emitted. **No train/validation/holdout, no learned improvement, no real-photo test.** Next: multi-family 12/6/6 real-render split, equal-budget ABAB; do not promote replay policy upstream.

### Domain-review enforcement — verified downstream (2026-10-19)

- **CI GREEN / DOWNSTREAM DRAFT:** [fork PR #45](https://github.com/kvnloo/img2threejs/pull/45) at exact head `6377a268c11f7f8736f2e0ef59aefb8eb3883437`, [native full Python + Node 18/22 CI](https://github.com/kvnloo/img2threejs/actions/runs/39212751779) and [close-policy workflow](https://github.com/kvnloo/img2threejs/actions/runs/39212751746) passed. Addresses [#122](https://github.com/img2threejs/img2threejs/issues/122), originally reported by @kokorolx; one existing contribution intent [#154](https://github.com/img2threejs/img2threejs/issues/154). Fourteen deterministic regressions cover non-generic profile continue requirements, null/rejected reports, legacy generic and stateless calls, non-continue actions, and missing/malformed state. Real plugin-backed end-to-end gate remains **not tested**; wait for maintainer triage, no new upstream PR.
- **EXPORTER DEDUP:** [fork PR #36](https://github.com/kvnloo/img2threejs/pull/36) closed **without merge**, retaining its branch, tests and commits for credit and salvage. [#35](https://github.com/kvnloo/img2threejs/pull/35) is the CLI-compatible carrier for source issue #90; [#39](https://github.com/kvnloo/img2threejs/pull/39) remains an alternative for possible instancing/root-capture salvage. No second origin submission or visual claim.

### Still needs evidence, tests, or triage

- **CHECK:** [#11](https://github.com/kvnloo/img2threejs/pull/11) head `a3c9bbf40387b5ffe70e75c6b423dc0fd1bf9208`, [CI #39200578418](https://github.com/kvnloo/img2threejs/actions/runs/39200578418) green; validator backward-compatibility decision needed.
- **CHECK:** [#12](https://github.com/kvnloo/img2threejs/pull/12) head `09679a4947cd0b6d2d2b93dbba162af836776169`, [CI #39201493165](https://github.com/kvnloo/img2threejs/actions/runs/39201493165) green; corrected interior-only masking opt-in, needs real crop comparison.
- **CHECK:** [#13](https://github.com/kvnloo/img2threejs/pull/13) head `c4f6c88e317397081215ffd98df82a147abd4027`, native Python CI green; needs unknown-family material tests and maintainer scope.
- **CHECK:** [#14](https://github.com/kvnloo/img2threejs/pull/14) head `4a127625f8769c37a68ed0b1fdaf39b41a7294d5`, native Python CI green; needs actual matte material render verification.
- **LIMITED:** [#16](https://github.com/kvnloo/img2threejs/pull/16) head `7511186991133b1cde881bfb410a9200ee6de9de` at this audit, still requires genuine external-producer evidence and equal-budget score-parity demonstration. Do not mistake #15's generated WebGL depth evidence for real Depth Anything/ComfyUI inference.
- **NEW / NO PROMOTION ASSERTED:** [#17](https://github.com/kvnloo/img2threejs/pull/17) curve-sweep correction; [#18](https://github.com/kvnloo/img2threejs/pull/18) Pocket World experiment; both draft and independently active. [#19](https://github.com/kvnloo/img2threejs/pull/19) closed; preserve provenance.
- **REGISTRATION PROPOSED, NOT MERGED:** [factory draft #197](https://github.com/kvnloo/oss-factory/pull/197).

### Outcome receipt

This wave refreshed two existing fork PRs, removed upstream-base drift, repaired security-adjacent filename handling and ran verified native CI. Refreshed existing upstream PR #149 with passing **fork** CI but did not approve its upstream workflow. Built and verified the first genuine WebGL2→Divine Eye procedural reference test with full screenshot and replay records. **Upstream merges: 0 verified. New upstream PRs: 0.** Maintainer-controlled origin CI/triage and substantive real-world multi-scene holdout remain the gates.

Do not open further duplicate origin intent tickets. Keep all source authors and reviewers credited via linked original issues and PRs. Never reclassify a passing synthetic or single-world probe as broad reconstruction fidelity.

---

## Historical audit and prior wave receipts (superseded by current wave above)

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
