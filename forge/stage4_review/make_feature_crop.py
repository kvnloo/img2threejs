#!/usr/bin/env python3
"""Package feature-level comparison crops using the full sheet's exact cover transform.

ROI and optional landmarks use normalized *panel* coordinates, NOT source-image
coordinates. This keeps both crops tied to what make_comparison_sheet.py actually
shows. One landmark can detect translation, but cannot prove camera registration,
3-D correspondence, or visual acceptance.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from make_comparison_sheet import load_image, resize_cover, write_png_rgb


def parse_coords(raw: str, count: int, label: str) -> tuple[float, ...]:
    try:
        values = tuple(float(part.strip()) for part in raw.split(","))
    except ValueError as exc:
        raise ValueError(f"{label} must be {count} comma-separated numbers") from exc
    if len(values) != count or any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValueError(f"{label} must contain {count} finite values in [0, 1]")
    return values


def crop_box(roi: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = roi
    if x0 >= x1 or y0 >= y1:
        raise ValueError("feature ROI requires x0 < x1 and y0 < y1")
    # Floor the leading edge, ceil the trailing edge: no relevant panel pixel
    # is discarded by floating-point rounding at ROI boundaries.
    left = math.floor(x0 * width)
    top = math.floor(y0 * height)
    right = math.ceil(x1 * width)
    bottom = math.ceil(y1 * height)
    if right <= left or bottom <= top:
        raise ValueError("feature ROI has no pixels at this panel resolution")
    return left, top, right, bottom


def crop_panel(
    pixels: list[tuple[int, int, int]], width: int, box: tuple[int, int, int, int]
) -> list[tuple[int, int, int]]:
    left, top, right, bottom = box
    return [
        pixels[y * width + x]
        for y in range(top, bottom)
        for x in range(left, right)
    ]


def landmark_pixel(coords: tuple[float, float], width: int, height: int) -> tuple[int, int]:
    return min(width - 1, math.floor(coords[0] * width)), min(height - 1, math.floor(coords[1] * height))


def create_feature_crop(
    reference: Path,
    render: Path,
    output: Path,
    *,
    roi: tuple[float, float, float, float],
    panel_width: int = 720,
    panel_height: int = 720,
    gutter: int = 24,
    reference_landmark: tuple[float, float] | None = None,
    render_landmark: tuple[float, float] | None = None,
    tolerance_px: int = 3,
) -> dict:
    if panel_width < 1 or panel_height < 1 or gutter < 0 or tolerance_px < 0:
        raise ValueError("panel dimensions must be positive; gutter/tolerance must be non-negative")
    if (reference_landmark is None) != (render_landmark is None):
        raise ValueError("provide both reference and render landmarks, or neither")
    if any(not math.isfinite(x) or not 0 <= x <= 1 for x in roi):
        raise ValueError("feature ROI coordinates must be finite values in [0, 1]")
    box = crop_box(roi, panel_width, panel_height)
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    alignment = {"status": "unverified", "landmarkErrorPx": None}
    if reference_landmark is not None and render_landmark is not None:
        for coords in (reference_landmark, render_landmark):
            if any(not math.isfinite(x) or not 0 <= x <= 1 for x in coords):
                raise ValueError("landmarks must be normalized panel coordinates in [0, 1]")
        a = landmark_pixel(reference_landmark, panel_width, panel_height)
        b = landmark_pixel(render_landmark, panel_width, panel_height)
        if not all(left <= x < right and top <= y < bottom for x, y in (a, b)):
            raise ValueError("both landmarks must lie inside the requested feature ROI")
        error = math.hypot(a[0] - b[0], a[1] - b[1])
        if error > tolerance_px:
            raise ValueError(f"landmark mismatch: {error:.2f}px exceeds {tolerance_px}px tolerance")
        alignment = {
            "status": "single-landmark-within-tolerance",
            "landmarkErrorPx": round(error, 3),
        }

    ref_w, ref_h, ref_pixels = load_image(reference)
    ren_w, ren_h, ren_pixels = load_image(render)
    ref_panel = resize_cover(ref_w, ref_h, ref_pixels, panel_width, panel_height)
    ren_panel = resize_cover(ren_w, ren_h, ren_pixels, panel_width, panel_height)
    ref_crop = crop_panel(ref_panel, panel_width, box)
    ren_crop = crop_panel(ren_panel, panel_width, box)
    canvas_width = width * 2 + gutter
    canvas = [(245, 245, 245)] * (canvas_width * height)
    for y in range(height):
        row = y * canvas_width
        start = y * width
        canvas[row : row + width] = ref_crop[start : start + width]
        canvas[row + width + gutter : row + width * 2 + gutter] = ren_crop[start : start + width]
    write_png_rgb(output, canvas_width, height, canvas)

    # Magnifying a small screenshot cannot manufacture missing reference detail.
    source_footprints = []
    for source_w, source_h in ((ref_w, ref_h), (ren_w, ren_h)):
        scale = max(panel_width / source_w, panel_height / source_h)
        source_footprints.append({
            "width": round(width / scale, 2),
            "height": round(height / scale, 2),
        })
    return {
        "comparisonImage": str(output.resolve()),
        "referenceImage": str(reference.resolve()),
        "renderScreenshot": str(render.resolve()),
        "layout": "left=reference,right=render",
        "roiSpace": "normalized-cover-panel",
        "roi": list(roi),
        "pixelRoi": list(box),
        "panelWidth": panel_width,
        "panelHeight": panel_height,
        "sourcePixelFootprints": source_footprints,
        "minimumSourceDetail128px": all(
            min(footprint.values()) >= 128 for footprint in source_footprints
        ),
        "alignment": alignment,
        "automaticAcceptance": False,
        "note": (
            "Pixels are sampled from the exact resize_cover panels used by "
            "make_comparison_sheet.py. Unverified or single-landmark alignment "
            "cannot prove camera registration; reviewer must validate correspondence. "
            "No quality score is computed."
        ),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--render", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--roi", required=True, help="normalized comparison-panel x0,y0,x1,y1")
    parser.add_argument("--panel-width", type=int, default=720)
    parser.add_argument("--panel-height", type=int, default=720)
    parser.add_argument("--gutter", type=int, default=24)
    parser.add_argument("--reference-landmark", help="normalized panel landmark x,y")
    parser.add_argument("--render-landmark", help="normalized panel landmark x,y")
    parser.add_argument("--tolerance-px", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = create_feature_crop(
            args.reference.expanduser().resolve(),
            args.render.expanduser().resolve(),
            args.out.expanduser().resolve(),
            roi=parse_coords(args.roi, 4, "--roi"),
            panel_width=args.panel_width,
            panel_height=args.panel_height,
            gutter=args.gutter,
            reference_landmark=(
                parse_coords(args.reference_landmark, 2, "--reference-landmark")
                if args.reference_landmark is not None else None
            ),
            render_landmark=(
                parse_coords(args.render_landmark, 2, "--render-landmark")
                if args.render_landmark is not None else None
            ),
            tolerance_px=args.tolerance_px,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2) if args.json else report["comparisonImage"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
