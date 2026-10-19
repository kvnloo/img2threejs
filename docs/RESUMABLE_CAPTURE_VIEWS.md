# Resuming a partial multi-view browser capture

Refs [upstream #165](https://github.com/img2threejs/img2threejs/issues/165).

After an interruption, run:

```bash
python3 forge/stage4_review/plan_capture_resume.py --manifest render-manifest.json
```

The JSON `next` entry identifies the first view requiring a screenshot.
For an image reference, it schedules one procedural shot per view in the existing
manifest order. For a GLB reference, it schedules browser-rendered reference
baselines **before** procedural shots of each view.

Only shots with a recorded status, browser-ready signal equal to **Boolean true**
(not the strings "true"/"false" or number 1), no browser
console errors, a readable saved screenshot, an unchanged SHA-256, and matching
recorded image type/width/height are skipped. Missing/unready/changed shots
and receipts with missing or mismatched image metadata are requeued. The manifest and the PNG
files are never edited by this planner, so a timeout cannot discard previously
valid captures.

For `glb-mediated-v2` manifests, the planner also verifies the published
`renderProfile.path` against `renderProfile.sha256`. A changed or missing profile
invalidates the entire resume: a screenshot with an intact hash is **not**
comparable when the shared camera/lighting contract has changed. Initialize a
new governed capture manifest rather than relabeling stale captures.

An actual browser adapter still must await the viewer's runtime-ready signal,
save the screenshot, and use `render_bridge.py record` or `record-reference`
to persist a truthful ready receipt. Re-run the planner after each completed
view. Never set ready=true merely to bypass a slow or failed browser render.

`captureShotsComplete` means **only** that the ordinary view screenshots are
available. It does not cover optional diagnostic render passes, calibrated
camera equivalence, landmark alignment or AI-vision fidelity gates;
`fullReviewPassed` is deliberately always false.

The command exits zero for a valid manifest even with pending work; malformed
manifests fail with exit code 2. No external downloads or Playwright dependency
are introduced.
