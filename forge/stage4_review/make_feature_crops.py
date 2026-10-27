#!/usr/bin/env python3
"""Extract matched feature crops from an existing comparison sheet.

Crop the already-composited panels, not separately resized source images. This
reuses the exact scaling/cropping/letterboxing that made the review sheet.
Landmarks are supplied in normalized *panel* coordinates, not source pixels.
Two distinct matched landmarks must agree within the tolerance before this
produces a feature-review artifact. This does not verify 3D camera registration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from make_comparison_sheet import read_png, write_png_rgb


def _point(value: object) -> tuple[float, float]:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(not isinstance(n, (int, float)) or isinstance(n, bool)
                   or not math.isfinite(n) or not 0 <= n <= 1 for n in value)):
        raise ValueError("landmark coordinates must be finite normalized [x, y] pairs")
    return float(value[0]), float(value[1])


def _rectangle(roi: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    if (len(roi) != 4 or any(not math.isfinite(n) for n in roi)
            or not 0 <= roi[0] < roi[2] <= 1
            or not 0 <= roi[1] < roi[3] <= 1):
        raise ValueError("ROI must be normalized x0 y0 x1 y1 with nonzero area")
    x0, y0 = math.floor(roi[0] * width), math.floor(roi[1] * height)
    x1, y1 = math.ceil(roi[2] * width), math.ceil(roi[3] * height)
    if x1 - x0 < 8 or y1 - y0 < 8:
        raise ValueError("feature ROI must cover at least 8x8 panel pixels")
    return x0, y0, x1, y1


def _check_landmarks(
    landmarks: object, roi: tuple[float, float, float, float],
    panel_w: int, panel_h: int, tolerance: float,
) -> float:
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("alignment tolerance must be finite and nonnegative")
    if not isinstance(landmarks, list) or len(landmarks) < 2:
        raise ValueError("at least two matched landmark pairs are required")
    ref_points: list[tuple[float, float]] = []
    render_points: list[tuple[float, float]] = []
    errors: list[float] = []
    for index, pair in enumerate(landmarks):
        if not isinstance(pair, dict):
            raise ValueError(f"landmark {index} must contain reference and render coordinates")
        ref = _point(pair.get("reference"))
        ren = _point(pair.get("render"))
        if not all(roi[0] <= pt[0] <= roi[2] and roi[1] <= pt[1] <= roi[3]
                   for pt in (ref, ren)):
            raise ValueError(f"landmark {index} falls outside the feature ROI")
        error = math.hypot((ref[0] - ren[0]) * panel_w, (ref[1] - ren[1]) * panel_h)
        if error > tolerance:
            raise ValueError(
                f"landmark {index} is misaligned by {error:.2f}px (limit {tolerance:.2f}px)"
            )
        ref_points.append(ref)
        render_points.append(ren)
        errors.append(error)
    # A duplicated point cannot establish the local scale/orientation of a feature.
    for points in (ref_points, render_points):
        separation = max(
            math.hypot((a[0] - b[0]) * panel_w, (a[1] - b[1]) * panel_h)
            for i, a in enumerate(points) for b in points[i + 1:]
        )
        if separation < 8:
            raise ValueError("landmark pairs must span at least 8 panel pixels")
    return max(errors)


def create_feature_crop(
    sheet: Path,
    manifest: dict,
    out: Path,
    roi: tuple[float, float, float, float],
    landmarks: list[dict],
    max_alignment_px: float = 8.0,
) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("comparison manifest must be a JSON object")
    recorded_sheet = manifest.get("comparisonImage")
    if not isinstance(recorded_sheet, str) or not recorded_sheet.strip():
        raise ValueError("comparison manifest must include comparisonImage")
    if Path(recorded_sheet).expanduser().resolve() != sheet.expanduser().resolve():
        raise ValueError("comparison manifest points to a different sheet")
    source_sha256 = hashlib.sha256(sheet.read_bytes()).hexdigest()
    expected_sha256 = manifest.get("comparisonSha256")
    if expected_sha256 is not None:
        if (not isinstance(expected_sha256, str)
                or len(expected_sha256) != 64
                or any(char not in "0123456789abcdefABCDEF" for char in expected_sha256)):
            raise ValueError("comparisonSha256 must be 64 hexadecimal characters")
        if source_sha256 != expected_sha256.lower():
            raise ValueError("comparison sheet SHA-256 disagrees with manifest")
    if manifest.get("layout") != "left=reference,right=render":
        raise ValueError("expected a left=reference,right=render comparison manifest")
    panel_w, panel_h = manifest.get("panelWidth"), manifest.get("panelHeight")
    if any(type(size) is not int or size <= 0 for size in (panel_w, panel_h)):
        raise ValueError("manifest panelWidth and panelHeight must be positive integers")
    sheet_w, sheet_h, pixels = read_png(sheet)
    if hashlib.sha256(sheet.read_bytes()).hexdigest() != source_sha256:
        raise ValueError("comparison sheet changed during crop extraction")
    leftover = sheet_w - 2 * panel_w
    if leftover < 0 or leftover % 3 != 0:
        raise ValueError("sheet width does not match the comparison manifest")
    gutter = leftover // 3
    header = sheet_h - panel_h - 2 * gutter
    if gutter < 6 or header < 0:
        raise ValueError("sheet dimensions do not match the comparison layout")
    box = _rectangle(roi, panel_w, panel_h)
    alignment = _check_landmarks(landmarks, roi, panel_w, panel_h, max_alignment_px)
    left, top, right, bottom = box
    crop_w, crop_h = right - left, bottom - top
    output_w = crop_w * 2 + gutter
    output: list[tuple[int, int, int]] = []
    panel_y = gutter + header
    for y in range(crop_h):
        sheet_y = panel_y + top + y
        for panel_x in (gutter, 2 * gutter + panel_w):
            first = sheet_y * sheet_w + panel_x + left
            output.extend(pixel[:3] for pixel in pixels[first:first + crop_w])
            if panel_x == gutter:
                output.extend([(246, 242, 236)] * gutter)
    write_png_rgb(out, output_w, crop_h, output)
    return {
        "featureImage": str(out.resolve()),
        "sourceComparison": str(sheet.resolve()),
        "sourceComparisonSha256": source_sha256,
        "layout": "left=reference,right=render",
        "roiPanelPixels": [left, top, right, bottom],
        "width": output_w,
        "height": crop_h,
        "landmarkPairs": len(landmarks),
        "maxAlignmentErrorPx": round(alignment, 4),
        "cameraRegistration": "not verified; supply a camera/landmark calibration separately",
        "note": "Feature comparison only; a crop is not a passing visual gate.",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True, help="JSON output of make_comparison_sheet.py --json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--roi", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"), required=True)
    parser.add_argument("--landmarks-json", type=Path, required=True,
                        help="JSON list of {reference:[x,y],render:[x,y]} normalized panel pairs")
    parser.add_argument("--max-alignment-px", type=float, default=8.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        landmarks = json.loads(args.landmarks_json.read_text(encoding="utf-8"))
        result = create_feature_crop(
            args.sheet, manifest, args.out, tuple(args.roi), landmarks, args.max_alignment_px,
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2) if args.json else result["featureImage"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
