# Sheet-aligned feature crops (downstream experiment)

Refs [upstream issue #165](https://github.com/img2threejs/img2threejs/issues/165).
This helper fixes one narrow evidence failure: a feature crop must use the same
center-**cover** sampling as `make_comparison_sheet.py`, not an assumed
contain/letterbox transform.

## Usage

First create or inspect your ordinary full comparison sheet. Choose the feature
rectangle **within the left/right panel**, excluding the sheet's header/gutter.
With the default panel size, its local coordinates run from 0 through 719.

```bash
python3 forge/stage4_review/make_feature_crops.py \
  --reference reference.png --render render.png \
  --panel-width 720 --panel-height 720 \
  --crop 310 190 96 120 --zoom 3 \
  --out-dir review-evidence/guard
```

The command writes `reference-feature.png`, `render-feature.png`,
`feature-comparison.png`, and `feature-crop-manifest.json`. It resizes both
originals through the **existing** `resize_cover` function before cropping
the same panel-space rectangle, preserving exact source-pixel choices. Zoom is
nearest-neighbor, not an image-reconstruction or hallucination filter.
The manifest records input hashes, native dimensions, panel dimensions and ROI.

## What this does not prove

Equal panel coordinates **do not establish camera, landmark, or world-space
correspondence** if the original reference and render use different framing or
views. The helper explicitly emits `landmarkAlignment: not verified` and
`cameraCorrespondence: not verified`. Reviewers must not use the resulting
images to assert local visual-fidelity acceptance until the view/camera and
landmarks have been independently verified. This is a correction to the
misaligned zoom evidence identified in #165, not a replacement for its
camera/world-to-screen projection or resumed per-view capture work.

Use only images you have the rights to process; avoid committing private
references or extracted proprietary pixels as test fixtures.
