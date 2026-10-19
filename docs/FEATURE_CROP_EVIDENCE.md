# Feature crops for image-led review (experimental)

`forge/stage4_review/make_feature_crops.py` packages named zoom views of a reference and render. It is a **review aid, not a visual score, pixel alignment proof, or acceptance gate**. It addresses the misaligned manually computed crops in #165 without changing `make_comparison_sheet.py` or the procedural builder.

Use measured landmarks from the **rendered comparison panels after fitting**, not pixel coordinates from the original files. Explicitly provide *independent* reference and render centers: those images can have different camera/framing offsets, and silently using the same center on both can create false evidence.

```json
{
  "schemaVersion": 1,
  "features": [
    {
      "id": "blade-tip",
      "referencePanelCenter": [0.72, 0.50],
      "renderPanelCenter": [0.70, 0.49]
    }
  ]
}
```

Values are normalized to `0..1` across the full fitted panel (top-left to bottom-right). Place the manifest at `features.json`, then run:

```bash
python3 forge/stage4_review/make_feature_crops.py \
  --reference reference.png --render render.png \
  --features-json features.json --out-dir feature-crops \
  --panel-width 720 --panel-height 720 --crop-size 160 --json
```

Outputs: `feature-crops/blade-tip.png` (left reference / right render, at the panel's sampled pixel resolution) and `feature-crops/feature-crops.json` (coordinates, image basenames, source sample pixels, resize mode, and explicit non-scoring notice). Feature IDs are path-safe and unique; malformed/ambiguous landmarks are refused. Crops outside the panel or inside letterbox margins are refused; choose a smaller crop or landmark inside the rendered content instead of generating misleading evidence.

The helper reuses the *actual* fit routine from `make_comparison_sheet.py`: current `resize_cover` or `resize_contain` when #73 lands. It does not guess which mode a manually assembled crop used. The report records the fit mode. This does not solve camera calibration or decide if the reference and render are semantically aligned; those remain reviewer responsibilities.

For targeted tests (stdlib only):

```bash
python3 -m unittest discover -s forge/tests -p 'test_feature_crop_geometry.py'
```
