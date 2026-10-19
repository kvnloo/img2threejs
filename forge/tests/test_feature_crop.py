"""Feature crops must replay the same cover pixels as the full comparison sheet."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

STAGE4 = Path(__file__).resolve().parents[1] / "stage4_review"
sys.path.insert(0, str(STAGE4))

from make_comparison_sheet import load_image, resize_cover, write_png_rgb  # noqa: E402
from make_feature_crop import create_feature_crop, parse_coords  # noqa: E402


class FeatureCropTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.reference = self.path / "reference.png"
        self.render = self.path / "render.png"
        self.output = self.path / "zoom.png"
        # Different image aspect ratios force distinct center-crop offsets.
        write_png_rgb(
            self.reference, 16, 8,
            [(x * 12, y * 27, 90) for y in range(8) for x in range(16)],
        )
        write_png_rgb(
            self.render, 8, 16,
            [(x * 24, y * 11, 100) for y in range(16) for x in range(8)],
        )

    def test_feature_pixels_match_the_exact_comparison_sheet_panels(self) -> None:
        report = create_feature_crop(
            self.reference, self.render, self.output,
            roi=(0.25, 0.25, 0.75, 0.75),
            panel_width=128, panel_height=128, gutter=8,
        )
        self.assertEqual(report["pixelRoi"], [32, 32, 96, 96])
        self.assertEqual(report["alignment"]["status"], "unverified")
        width, height, output_pixels = load_image(self.output)
        self.assertEqual((width, height), (136, 64))
        for path, offset in ((self.reference, 0), (self.render, 72)):
            source_w, source_h, source = load_image(path)
            panel = resize_cover(source_w, source_h, source, 128, 128)
            for y in range(64):
                for x in range(64):
                    actual = output_pixels[y * width + x + offset][:3]
                    expected = panel[(y + 32) * 128 + (x + 32)]
                    self.assertEqual(actual, expected)

    def test_landmark_check_rejects_misaligned_comparison(self) -> None:
        with self.assertRaisesRegex(ValueError, "landmark mismatch"):
            create_feature_crop(
                self.reference, self.render, self.output,
                roi=(0.1, 0.1, 0.9, 0.9),
                panel_width=128, panel_height=128,
                reference_landmark=(0.3, 0.4),
                render_landmark=(0.5, 0.4),
                tolerance_px=3,
            )
        self.assertFalse(self.output.exists())

    def test_landmarks_require_a_pair_and_roi_membership(self) -> None:
        with self.assertRaisesRegex(ValueError, "both reference and render"):
            create_feature_crop(
                self.reference, self.render, self.output,
                roi=(0.1, 0.1, 0.9, 0.9),
                reference_landmark=(0.2, 0.2),
            )
        with self.assertRaisesRegex(ValueError, "inside"):
            create_feature_crop(
                self.reference, self.render, self.output,
                roi=(0.1, 0.1, 0.4, 0.4),
                reference_landmark=(0.7, 0.7), render_landmark=(0.7, 0.7),
            )

    def test_matching_landmark_reports_limited_coverage_not_visual_acceptance(self) -> None:
        report = create_feature_crop(
            self.reference, self.render, self.output,
            roi=(0.2, 0.2, 0.8, 0.8),
            panel_width=128, panel_height=128,
            reference_landmark=(0.5, 0.5), render_landmark=(0.5, 0.5),
        )
        self.assertEqual(report["alignment"]["status"], "single-landmark-within-tolerance")
        self.assertEqual(report["alignment"]["landmarkErrorPx"], 0)
        self.assertFalse(report["minimumSourceDetail128px"])
        self.assertFalse(report["automaticAcceptance"])

    def test_invalid_roi_and_non_finite_numbers_fail_closed(self) -> None:
        for roi in ((0.5, 0.5, 0.5, 0.6), (-0.2, 0.1, 0.8, 0.8), (0.1, 0.2, 1.2, 0.8)):
            with self.subTest(roi=roi), self.assertRaises(ValueError):
                create_feature_crop(self.reference, self.render, self.output, roi=roi)
        with self.assertRaises(ValueError):
            parse_coords("nan,0.2,0.5,0.6", 4, "--roi")
        with self.assertRaises(ValueError):
            parse_coords("0.1,0.2,0.3", 4, "--roi")
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
