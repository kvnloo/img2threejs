# Crash-safe browser capture checkpoints

Refs [img2threejs/img2threejs#165](https://github.com/img2threejs/img2threejs/issues/165).
The camera-batch failure and evidence-loss problem was documented by @kokorolx.

`scripts/capture_threejs_playwright.py` now persists the render manifest
**after each successful beauty screenshot and each diagnostic pass**, rather
than only at the end of a multi-camera run. The existing
`write_manifest()` temporary-file replacement supplies atomic updates.

If a later camera times out or a diagnostic pass raises an exception:

- Already recorded screenshots, their paths, hashes, readiness receipts,
  and completed diagnostic pass records remain in the manifest.
- A machine-readable `evidence.lastCaptureError` describes the most recent
  failed attempt; the CLI retains its nonzero failure exit.
- Pending shots and passes stay pending. No visual acceptance is inferred.
- The next successful capture removes the stale `lastCaptureError`.

Use `--capture-id hero` or another explicit camera ID when retrying an
individual view. The independent read-only resume planner in
[kvnloo/img2threejs#42](https://github.com/kvnloo/img2threejs/pull/42)
can choose the next view without repeating a known-good screenshot. That
planner is not part of this patch. It does not automatically resume a
browser, and neither tool proves correct camera calibration or likeness.

These regressions run without the optional Playwright package: the test
adapter simulates a timeout on the second camera, failure in a v2 diagnostic
pass, reference-mode capture, navigation failure, and a clean retry.

`python3 -m unittest forge.tests.test_capture_checkpoint`

A real browser-based end-to-end capture and crash/kill test is still needed
before claiming the full workflow is production-verified.
