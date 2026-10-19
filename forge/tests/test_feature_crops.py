#!/usr/bin/env python3
"""Sheet-space feature crops must match the actual resize_cover pixels (#165)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage4_review"))

from make_comparison_sheet import read_png, resize_cover, write_png_rgb  # noqa: E402
from make_feature_crops import create_feature_crop_pair  # noqa: E402


def _rgb(path: Path) -> list[tuple[int, int, int]]:
    return [pixel[:3] for pixel in read_png(path)[2]]


class FeatureCropTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.reference = self.folder / "reference.png"
        self.render = self.folder / "render.png"
        # Different input aspect ratios force opposite center-crop axes.
        self.reference_pixels = [(20 * x, 30 * y, 100) for y in range(2) for x in range(4)]
        self.render_pixels = [(100, 20 * x, 30 * y) for y in range(4) for x in range(2)]
        write_png_rgb(self.reference, 4, 2, self.reference_pixels)
        write_png_rgb(self.render, 2, 4, self.render_pixels)

    def test_crops_match_actual_resize_cover_sampling_on_both_panels(self):
        output = self.folder / "crops"
        result = create_feature_crop_pair(
            self.reference, self.render, output, panel_width=4, panel_height=4,
            x=1, y=1, width=2, height=2, zoom=2,
        )
        for path, size, original, key in (
            (self.reference, (4, 2), self.reference_pixels, "referenceCrop"),
            (self.render, (2, 4), self.render_pixels, "renderCrop"),
        ):
            panel = resize_cover(
                size[0], size[1], [(*pixel, 255) for pixel in original], 4, 4,
            )
            expected = []
            for y in range(1, 3):
                row = []
                for x in range(1, 3):
                    row.extend([panel[y * 4 + x]] * 2)
                expected.extend(row)
                expected.extend(row)
            crop = Path(result[key])
            self.assertEqual(read_png(crop)[:2], (4, 4))
            self.assertEqual(_rgb(crop), expected)
        self.assertEqual(result["sampling"],
                         "make_comparison_sheet.resize_cover then panel-coordinate crop")
        self.assertEqual(result["landmarkAlignment"], "not verified")
        self.assertEqual(result["cameraCorrespondence"], "not verified")
        self.assertEqual(len(result["reference"]["sha256"]), 64)
        self.assertEqual(
            json.loads((output / "feature-crop-manifest.json").read_text(encoding="utf-8")),
            result,
        )

    def test_combined_comparison_places_both_crop_images_without_resampling(self):
        result = create_feature_crop_pair(
            self.reference, self.render, self.folder / "out", panel_width=4,
            panel_height=4, x=0, y=0, width=2, height=2, zoom=1, gutter=1,
        )
        pair = Path(result["comparisonImage"])
        self.assertEqual(read_png(pair)[:2], (5, 2))
        pixels = _rgb(pair)
        left = _rgb(Path(result["referenceCrop"]))
        right = _rgb(Path(result["renderCrop"]))
        for row in range(2):
            self.assertEqual(pixels[row * 5 : row * 5 + 2], left[row * 2 : row * 2 + 2])
            self.assertEqual(pixels[row * 5 + 2], (240, 240, 240))
            self.assertEqual(pixels[row * 5 + 3 : row * 5 + 5],
                             right[row * 2 : row * 2 + 2])

    def test_out_of_bounds_roi_fails_without_writing_files(self):
        output = self.folder / "invalid"
        for params in (
            dict(x=-1, y=0, width=1, height=1),
            dict(x=3, y=0, width=2, height=1),
            dict(x=0, y=3, width=1, height=2),
            dict(x=0, y=0, width=0, height=1),
        ):
            with self.subTest(params=params):
                with self.assertRaises(ValueError):
                    create_feature_crop_pair(
                        self.reference, self.render, output, panel_width=4,
                        panel_height=4, **params,
                    )
        self.assertFalse(output.exists())

    def test_cli_writes_review_evidence(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "forge" / "stage4_review" / "make_feature_crops.py"),
             "--reference", str(self.reference), "--render", str(self.render),
             "--out-dir", str(self.folder / "cli"),
             "--panel-width", "4", "--panel-height", "4",
             "--crop", "1", "1", "2", "2", "--zoom", "2"],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(Path(payload["comparisonImage"]).is_file())
        self.assertEqual(payload["crop"], {"x": 1, "y": 1, "width": 2,
                                           "height": 2, "zoom": 2})


if __name__ == "__main__":
    unittest.main()
