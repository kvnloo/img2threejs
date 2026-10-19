#!/usr/bin/env python3
"""Produce feature crops in the exact pixel space of make_comparison_sheet.py.

The crop rectangle is measured on either 720x720 comparison panel, NOT in
original source-image pixels. Both images are passed through the canonical
resize_cover sampler before cropping, so a reviewer cannot accidentally use
contain geometry for evidence that was center-cropped. This aligns the panel
coordinate systems; it does not prove the two cameras or landmarks align.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from make_comparison_sheet import load_image, resize_cover, write_png_rgb


def _zoom_crop(
    panel: list[tuple[int, int, int]],
    panel_width: int,
    x: int,
    y: int,
    width: int,
    height: int,
    zoom: int,
) -> list[tuple[int, int, int]]:
    """Crop after resize_cover and enlarge by nearest-neighbor replication."""
    output: list[tuple[int, int, int]] = []
    for row in range(y, y + height):
        enlarged: list[tuple[int, int, int]] = []
        start = row * panel_width + x
        for pixel in panel[start : start + width]:
            enlarged.extend([pixel] * zoom)
        for _ in range(zoom):
            output.extend(enlarged)
    return output


def create_feature_crop_pair(
    reference: Path,
    render: Path,
    out_dir: Path,
    *,
    panel_width: int = 720,
    panel_height: int = 720,
    x: int,
    y: int,
    width: int,
    height: int,
    zoom: int = 3,
    gutter: int = 12,
) -> dict:
    """Save two sheet-aligned crops, a paired comparison, and provenance JSON."""
    if panel_width < 1 or panel_height < 1:
        raise ValueError("panel dimensions must be positive")
    if x < 0 or y < 0 or width < 1 or height < 1:
        raise ValueError("crop origin must be nonnegative and dimensions positive")
    if x + width > panel_width or y + height > panel_height:
        raise ValueError("crop rectangle must fit inside the comparison panel")
    if not 1 <= zoom <= 8:
        raise ValueError("zoom must be an integer from 1 to 8")
    if not 0 <= gutter <= 128:
        raise ValueError("gutter must be from 0 to 128")

    crops: list[list[tuple[int, int, int]]] = []
    inputs: list[dict] = []
    for path in (reference, render):
        native_width, native_height, pixels = load_image(path)
        panel = resize_cover(native_width, native_height, pixels, panel_width, panel_height)
        crops.append(_zoom_crop(panel, panel_width, x, y, width, height, zoom))
        inputs.append({
            "path": str(path.resolve()),
            "width": native_width,
            "height": native_height,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    cropped_w, cropped_h = width * zoom, height * zoom
    ref_crop, ren_crop = crops
    ref_out = out_dir / "reference-feature.png"
    ren_out = out_dir / "render-feature.png"
    pair_out = out_dir / "feature-comparison.png"
    write_png_rgb(ref_out, cropped_w, cropped_h, ref_crop)
    write_png_rgb(ren_out, cropped_w, cropped_h, ren_crop)

    paired: list[tuple[int, int, int]] = []
    separator = [(240, 240, 240)] * gutter
    for row in range(cropped_h):
        start = row * cropped_w
        paired.extend(ref_crop[start : start + cropped_w])
        paired.extend(separator)
        paired.extend(ren_crop[start : start + cropped_w])
    write_png_rgb(pair_out, cropped_w * 2 + gutter, cropped_h, paired)

    result = {
        "comparisonImage": str(pair_out.resolve()),
        "referenceCrop": str(ref_out.resolve()),
        "renderCrop": str(ren_out.resolve()),
        "reference": inputs[0],
        "render": inputs[1],
        "panel": {"width": panel_width, "height": panel_height},
        "crop": {"x": x, "y": y, "width": width, "height": height, "zoom": zoom},
        "sampling": "make_comparison_sheet.resize_cover then panel-coordinate crop",
        "landmarkAlignment": "not verified",
        "cameraCorrespondence": "not verified",
        "note": "Pixel-aligned to comparison panels only; do not claim feature or camera alignment without independent checks.",
    }
    (out_dir / "feature-crop-manifest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--render", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--panel-width", type=int, default=720)
    parser.add_argument("--panel-height", type=int, default=720)
    parser.add_argument("--crop", type=int, nargs=4, required=True, metavar=("X", "Y", "W", "H"),
                        help="rectangle in each comparison panel's pixel coordinates")
    parser.add_argument("--zoom", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        result = create_feature_crop_pair(
            args.reference.expanduser(),
            args.render.expanduser(),
            args.out_dir.expanduser(),
            panel_width=args.panel_width,
            panel_height=args.panel_height,
            x=args.crop[0],
            y=args.crop[1],
            width=args.crop[2],
            height=args.crop[3],
            zoom=args.zoom,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
