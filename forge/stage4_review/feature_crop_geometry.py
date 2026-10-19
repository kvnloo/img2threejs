"""Deterministic feature crop coordinates for img2threejs comparison panels.

Coordinates are normalized *post-fit panel* coordinates, never raw-image coordinates.
The same sampling formulas are used by make_comparison_sheet.py (cover on main,
contain in PR #73). This module never makes a visual-fidelity score.
"""

from __future__ import annotations

import math
import re
from typing import Any

_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}\Z")


def parse_features(manifest: Any) -> list[dict[str, Any]]:
    """Validate a manifest, including dual independent panel-space landmarks."""
    if not isinstance(manifest, dict) or type(manifest.get("schemaVersion")) is not int or manifest["schemaVersion"] != 1:
        raise ValueError("schemaVersion must be 1")
    features = manifest.get("features")
    if not isinstance(features, list) or not (1 <= len(features) <= 32):
        raise ValueError("features must contain between 1 and 32 entries")
    ids = set()
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get("id"), str) or not _ID.fullmatch(feature["id"]):
            raise ValueError("feature id must be a safe 1-48 character identifier")
        if feature["id"] in ids:
            raise ValueError(f"duplicate feature id: {feature['id']}")
        ids.add(feature["id"])
        for key in ("referencePanelCenter", "renderPanelCenter"):
            point = feature.get(key)
            if (not isinstance(point, list) or len(point) != 2 or
                    any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 or v > 1 for v in point)):
                raise ValueError(f"feature {feature['id']} {key} must contain two finite normalized numbers")
    return features


def _positive_dimensions(*sizes: int) -> None:
    if any(type(n) is not int or n <= 0 for n in sizes):
        raise ValueError("dimensions must be positive integers")


def fit_rect(src_w: int, src_h: int, panel_w: int, panel_h: int, fit: str) -> tuple[int, int, int, int, float]:
    """Replicate make_comparison_sheet's exact rounded scale and panel offsets."""
    _positive_dimensions(src_w, src_h, panel_w, panel_h)
    if fit not in ("cover", "contain"):
        raise ValueError("fit must be cover or contain")
    scale = (max if fit == "cover" else min)(panel_w / src_w, panel_h / src_h)
    scaled_w = max(1, round(src_w * scale))
    scaled_h = max(1, round(src_h * scale))
    offset_x = ((scaled_w - panel_w) // 2 if fit == "cover" else (panel_w - scaled_w) // 2)
    offset_y = ((scaled_h - panel_h) // 2 if fit == "cover" else (panel_h - scaled_h) // 2)
    return offset_x, offset_y, scaled_w, scaled_h, scale


def panel_pixel(point: list[float], panel_w: int, panel_h: int) -> tuple[int, int]:
    _positive_dimensions(panel_w, panel_h)
    return round(point[0] * (panel_w - 1)), round(point[1] * (panel_h - 1))


def panel_to_source(
    point: list[float], src_w: int, src_h: int, panel_w: int, panel_h: int, fit: str
) -> tuple[int, int] | None:
    """Map a panel landmark to exactly the source pixel sampled by its sheet."""
    x, y = panel_pixel(point, panel_w, panel_h)
    ox, oy, sw, sh, scale = fit_rect(src_w, src_h, panel_w, panel_h, fit)
    if fit == "cover":
        return (min(src_w - 1, max(0, int((x + ox) / scale))),
                min(src_h - 1, max(0, int((y + oy) / scale))))
    if not (ox <= x < ox + sw and oy <= y < oy + sh):
        return None  # letterbox, not image data
    local_x, local_y = x - ox, y - oy
    return (0 if sw == 1 else round(local_x * (src_w - 1) / (sw - 1)),
            0 if sh == 1 else round(local_y * (src_h - 1) / (sh - 1)))


def crop_panel(
    pixels: list[tuple[int, int, int]], panel_w: int, panel_h: int,
    point: list[float], crop_size: int, content_rect: tuple[int, int, int, int] | None = None,
) -> list[tuple[int, int, int]]:
    """Crop the pixel-exact *already fitted* comparison panel without resampling."""
    _positive_dimensions(panel_w, panel_h, crop_size)
    if len(pixels) != panel_w * panel_h:
        raise ValueError("panel pixel count does not match dimensions")
    if crop_size > min(panel_w, panel_h):
        raise ValueError("crop size exceeds panel dimensions")
    cx, cy = panel_pixel(point, panel_w, panel_h)
    x0, y0 = cx - crop_size // 2, cy - crop_size // 2
    if x0 < 0 or y0 < 0 or x0 + crop_size > panel_w or y0 + crop_size > panel_h:
        raise ValueError("crop extends outside comparison panel")
    if content_rect is not None:
        bx, by, bw, bh = content_rect
        if x0 < bx or y0 < by or x0 + crop_size > bx + bw or y0 + crop_size > by + bh:
            raise ValueError("crop extends into letterbox (not reference evidence)")
    return [pixels[y * panel_w + x] for y in range(y0, y0 + crop_size) for x in range(x0, x0 + crop_size)]


def combine_crops(
    reference: list[tuple[int, int, int]], render: list[tuple[int, int, int]],
    crop_size: int, gutter: int = 16,
) -> tuple[int, int, list[tuple[int, int, int]]]:
    _positive_dimensions(crop_size, gutter)
    if len(reference) != crop_size ** 2 or len(render) != crop_size ** 2:
        raise ValueError("crop dimensions mismatch")
    width = crop_size * 2 + gutter
    background = (34, 42, 50)
    pixels = [background] * (width * crop_size)
    for y in range(crop_size):
        a = y * crop_size
        pixels[y * width : y * width + crop_size] = reference[a : a + crop_size]
        pixels[y * width + crop_size + gutter : (y + 1) * width] = render[a : a + crop_size]
    return width, crop_size, pixels
