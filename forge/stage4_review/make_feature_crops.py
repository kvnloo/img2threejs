#!/usr/bin/env python3
"""Emit pixel-exact anchored feature crops for a visual reviewer; never score them.

The comparison-sheet fit function is resolved at runtime to follow either
current resize_cover or the pending resize_contain implementation (#73).
Each feature must declare independent normalized PANEL landmarks for the
reference and render: never assume one image's pixel coordinates fit the other.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from feature_crop_geometry import (
    combine_crops, crop_panel, fit_rect, panel_to_source, parse_features,
)


def create_feature_crops(
    reference: Path, render: Path, features_json: Path, out_dir: Path,
    panel_w: int = 720, panel_h: int = 720, crop_size: int = 160,
) -> dict:
    if type(panel_w) is not int or type(panel_h) is not int or type(crop_size) is not int:
        raise ValueError("pixel sizes must be integers")
    if not (64 <= panel_w <= 1024 and 64 <= panel_h <= 1024 and 16 <= crop_size <= min(panel_w, panel_h)):
        raise ValueError("panel dimensions or crop size out of bounds")
    features = parse_features(json.loads(features_json.read_text(encoding="utf-8")))

    # Reuse the actual acceptance-sheet scaler, including any future contain migration.
    import make_comparison_sheet as sheet

    fit = "contain" if hasattr(sheet, "resize_contain") else "cover"
    sampler = sheet.resize_contain if fit == "contain" else sheet.resize_cover
    ref_w, ref_h, ref_pixels = sheet.load_image(reference)
    ren_w, ren_h, ren_pixels = sheet.load_image(render)
    ref_panel = sampler(ref_w, ref_h, ref_pixels, panel_w, panel_h)
    ren_panel = sampler(ren_w, ren_h, ren_pixels, panel_w, panel_h)

    def content_rect(src_w: int, src_h: int) -> tuple[int, int, int, int] | None:
        if fit == "cover":
            return None
        return fit_rect(src_w, src_h, panel_w, panel_h, fit)[:4]

    planned = []  # Validate and generate every crop before writing any PNG.
    for feature in features:
        name = feature["id"]
        ref_center, ren_center = feature["referencePanelCenter"], feature["renderPanelCenter"]
        try:
            ref_crop = crop_panel(ref_panel, panel_w, panel_h, ref_center, crop_size, content_rect(ref_w, ref_h))
            ren_crop = crop_panel(ren_panel, panel_w, panel_h, ren_center, crop_size, content_rect(ren_w, ren_h))
        except ValueError as exc:
            raise ValueError(f"feature {name}: {exc}") from exc
        width, height, pixels = combine_crops(ref_crop, ren_crop, crop_size)
        planned.append((name, width, height, pixels, ref_center, ren_center))

    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schemaVersion": 1,
        "coordinateSpace": "normalized-post-fit-comparison-panel",
        "fit": fit,
        "panelWidth": panel_w,
        "panelHeight": panel_h,
        "referenceImage": reference.name,
        "renderImage": render.name,
        "note": "Feature crops are review evidence, not scoring or proof of geometric alignment.",
        "features": [],
    }
    for name, width, height, pixels, ref_center, ren_center in planned:
        destination = out_dir / f"{name}.png"
        sheet.write_png_rgb(destination, width, height, pixels)
        report["features"].append({
            "id": name,
            "cropImage": destination.name,
            "cropPixels": crop_size,
            "referencePanelCenter": ref_center,
            "renderPanelCenter": ren_center,
            "referenceSamplePixel": panel_to_source(ref_center, ref_w, ref_h, panel_w, panel_h, fit),
            "renderSamplePixel": panel_to_source(ren_center, ren_w, ren_h, panel_w, panel_h, fit),
        })
    (out_dir / "feature-crops.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--render", required=True, type=Path)
    parser.add_argument("--features-json", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--panel-width", type=int, default=720)
    parser.add_argument("--panel-height", type=int, default=720)
    parser.add_argument("--crop-size", type=int, default=160)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = create_feature_crops(args.reference, args.render, args.features_json, args.out_dir,
                                      args.panel_width, args.panel_height, args.crop_size)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2) if args.json else str(args.out_dir / "feature-crops.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
