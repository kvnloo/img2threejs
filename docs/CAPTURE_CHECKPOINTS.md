# Crash-safe browser capture checkpoints

Refs [img2threejs/img2threejs#165](https://github.com/img2threejs/img2threejs/issues/165).
The camera-batch failure and evidence-loss problem was documented by kokorolx.

`scripts/capture_threejs_playwright.py` now persists the render manifest
**after each successful beauty screenshot and each diagnostic pass**, rather
than only at the end of a multi-camera run. The existing
`write_manifest()` temporary-file replacement supplies atomic updates.

If a later camera times out or a diagnostic pass raises an exception:

- Already recorded screenshots, their paths, hashes, readiness receipts,
  and completed diagnostic pass records remain in the manifest.
- A machine-readable `evidence.lastCaptureError` describes the most recent
  failed attempt; the CLI retains its nonzero failure exit.
- Unattempted shots and passes stay pending. An interrupted view is marked
  failed while retaining the successful screenshot/pass records for inspection.
  No visual acceptance is inferred.
- The next successful capture removes the stale `lastCaptureError`.

Use `--capture-id hero` or another explicit camera ID when retrying an
individual view. The follow-up in [kvnloo/img2threejs#48](https://github.com/kvnloo/img2threejs/pull/48)
adds `--resume` to the browser adapter, with matching input signatures,
strict browser readiness and fresh image-hash checks. It extends the original
checkpoints from [kvnloo/img2threejs#46](https://github.com/kvnloo/img2threejs/pull/46)
and keeps `lastCaptureError` alongside the richer `evidence.captureSession`.
The independent read-only resume planner in
[kvnloo/img2threejs#42](https://github.com/kvnloo/img2threejs/pull/42)
can choose the next view without repeating a known-good screenshot. That
planner remains a separate contribution. Neither tool proves correct camera
calibration or likeness.

Before browser launch or receipt invalidation, the resume adapter also
checks *every* planned screenshot/diagnostic destination, including unselected
views. It refuses destinations pointing at the original image/GLB, render
manifest, shared render profile, or another output. Existing **hard-linked**
paths are checked by file identity, not just resolved names: otherwise
two different paths can silently share an inode and overwrite protected
evidence. Preflight is a filesystem snapshot, not protection against
other processes modifying output paths concurrently.

These regressions run without the optional Playwright package: the test
adapter simulates a timeout on the second camera, failure in a v2 diagnostic
pass, reference-mode capture, navigation failure, and a clean retry.

`python3 -m unittest forge.tests.test_capture_checkpoint`

The opt-in `scripts/test_capture_resume_browser.py` additionally exercises
real Chromium/Three.js timeout recovery, verifies unchanged completed PNGs,
and checks corruption and readiness failures. See the
[render-bridge recovery instructions](../grimoire/build/python_threejs_render_bridge.md#recover-an-interrupted-capture-batch).
This bounded fixture does not establish arbitrary application crash recovery
or reconstruction fidelity.
