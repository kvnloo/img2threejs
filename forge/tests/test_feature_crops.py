"""Source-pixel-accurate feature crops for the stage-4 comparison sheet."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage4_review"))

from make_comparison_sheet import create_sheet, read_png, write_png_rgb  # noqa: E402
from make_feature_crops import create_feature_crop  # noqa: E402


class FeatureCropTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.sheet = self.dir / "comparison.png"
        self.ref = self.dir / "reference.png"
        self.render = self.dir / "render.png"
        self.out = self.dir / "feature.png"
        # Landscape reference and portrait render trigger independent cover crops.
        write_png_rgb(self.ref, 128, 32, [((x * 2) % 256, (y * 7) % 256, 25)
                                              for y in range(32) for x in range(128)])
        write_png_rgb(self.render, 32, 128, [(75, (x * 7) % 256, (y * 2) % 256)
                                               for y in range(128) for x in range(32)])
        self.manifest = create_sheet(self.ref, self.render, self.sheet, 64, 64, 6)
        self.roi = (0.25, 0.25, 0.75, 0.75)
        self.landmarks = [
            {"reference": [0.30, 0.30], "render": [0.30, 0.30]},
            {"reference": [0.70, 0.70], "render": [0.70, 0.70]},
        ]

    def test_crop_matches_exact_composited_sheet_pixels_in_both_panels(self):
        result = create_feature_crop(self.sheet, self.manifest, self.out, self.roi, self.landmarks)
        sw, _, sheet = read_png(self.sheet)
        w, h, feature = read_png(self.out)
        self.assertEqual((w, h), (70, 32))
        self.assertEqual(result["roiPanelPixels"], [16, 16, 48, 48])
        self.assertEqual(result["landmarkPairs"], 2)
        self.assertEqual(result["maxAlignmentErrorPx"], 0)
        # Compositing is the source of truth: no second cover/contain transform.
        for y in (0, 15, 31):
            for x in (0, 12, 31):
                original_y = y + 6 + 28 + 16
                self.assertEqual(feature[y * w + x][:3], sheet[original_y * sw + 6 + 16 + x][:3])
                self.assertEqual(feature[y * w + 38 + x][:3],
                                 sheet[original_y * sw + (12 + 64) + 16 + x][:3])
            self.assertEqual(feature[y * w + 32][:3], (246, 242, 236))

    def test_rejects_shifted_landmarks_without_writing_crop(self):
        self.landmarks[0]["render"] = [0.52, 0.30]
        with self.assertRaisesRegex(ValueError, "misaligned"):
            create_feature_crop(self.sheet, self.manifest, self.out, self.roi, self.landmarks)
        self.assertFalse(self.out.exists())

    def test_rejects_single_or_collapsed_landmark_pairs(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            create_feature_crop(self.sheet, self.manifest, self.out, self.roi, self.landmarks[:1])
        self.landmarks[1] = self.landmarks[0].copy()
        with self.assertRaisesRegex(ValueError, "span at least"):
            create_feature_crop(self.sheet, self.manifest, self.out, self.roi, self.landmarks)

    def test_rejects_invalid_region_and_sheet_layout(self):
        for roi in ((0.8, 0.2, 0.1, 0.5), (0.1, 0.1, 0.11, 0.11),
                    (float('nan'), 0, 1, 1)):
            with self.subTest(roi=roi), self.assertRaises(ValueError):
                create_feature_crop(self.sheet, self.manifest, self.out, roi, self.landmarks)
        with self.assertRaisesRegex(ValueError, "sheet width"):
            create_feature_crop(self.sheet, {**self.manifest, "panelWidth": 65},
                                self.out, self.roi, self.landmarks)

    def test_manifest_binds_source_sheet_and_optional_sha256(self):
        import hashlib

        other_sheet = self.dir / "same-pixels-different-sheet.png"
        other_sheet.write_bytes(self.sheet.read_bytes())
        with self.assertRaisesRegex(ValueError, "different sheet"):
            create_feature_crop(other_sheet, self.manifest, self.out, self.roi, self.landmarks)
        self.assertFalse(self.out.exists())

        checksum = hashlib.sha256(self.sheet.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "SHA-256 disagrees"):
            create_feature_crop(self.sheet, {**self.manifest, "comparisonSha256": "0" * 64},
                                self.out, self.roi, self.landmarks)
        with self.assertRaisesRegex(ValueError, "64 hexadecimal"):
            create_feature_crop(self.sheet, {**self.manifest, "comparisonSha256": "invalid"},
                                self.out, self.roi, self.landmarks)
        self.assertFalse(self.out.exists())

        evidence = create_feature_crop(
            self.sheet, {**self.manifest, "comparisonSha256": checksum.upper()},
            self.out, self.roi, self.landmarks,
        )
        self.assertEqual(evidence["sourceComparisonSha256"], checksum)

    def test_manifest_requires_object_and_explicit_sheet(self):
        with self.assertRaisesRegex(ValueError, "JSON object"):
            create_feature_crop(self.sheet, [], self.out, self.roi, self.landmarks)
        with self.assertRaisesRegex(ValueError, "comparisonImage"):
            create_feature_crop(self.sheet, {"layout": "left=reference,right=render"},
                                self.out, self.roi, self.landmarks)
        self.assertFalse(self.out.exists())

    def test_mutated_png_during_decode_fails_before_output(self):
        from unittest.mock import patch
        import make_feature_crops as crop_module

        original = crop_module.read_png

        def changing_read(path):
            result = original(path)
            # The decoded picture was from one snapshot, but the PNG on disk
            # changed before receipt generation. Refuse to bind stale evidence.
            path.write_bytes(path.read_bytes() + b"later-version")
            return result

        with patch.object(crop_module, "read_png", side_effect=changing_read):
            with self.assertRaisesRegex(ValueError, "changed during"):
                create_feature_crop(self.sheet, self.manifest, self.out, self.roi, self.landmarks)
        self.assertFalse(self.out.exists())

    def test_contain_letterbox_pixels_are_not_recomputed_as_cover(self):
        # Simulate upstream PR #73's contain-panel compositor, independently
        # of whether the current checkout exposes resize_cover or resize_contain.
        # The feature crop MUST copy the final panel pixels, not refit raw input.
        from make_comparison_sheet import blit

        sheet_w, sheet_h, pixels = read_png(self.sheet)
        modified = [pixel[:3] for pixel in pixels]

        def contain_panel(path):
            src_w, src_h, source = read_png(path)
            scale = min(64 / src_w, 64 / src_h)
            fit_w = max(1, round(src_w * scale))
            fit_h = max(1, round(src_h * scale))
            offset_x, offset_y = (64 - fit_w) // 2, (64 - fit_h) // 2
            panel = [(222, 223, 224)] * (64 * 64)
            for y in range(fit_h):
                source_y = 0 if fit_h == 1 else round(y * (src_h - 1) / (fit_h - 1))
                for x in range(fit_w):
                    source_x = 0 if fit_w == 1 else round(x * (src_w - 1) / (fit_w - 1))
                    panel[(y + offset_y) * 64 + x + offset_x] = source[source_y * src_w + source_x][:3]
            return panel

        blit(modified, sheet_w, contain_panel(self.ref), 64, 6, 34)
        blit(modified, sheet_w, contain_panel(self.render), 64, 76, 34)
        write_png_rgb(self.sheet, sheet_w, sheet_h, modified)

        result = create_feature_crop(self.sheet, self.manifest, self.out, self.roi, self.landmarks)
        width, height, output = read_png(self.out)
        self.assertEqual((width, height), (70, 32))
        self.assertEqual(result["roiPanelPixels"], [16, 16, 48, 48])
        # The top of the panoramic reference and left of the portrait render
        # are letterboxed; their synthetic padding must survive the crop.
        self.assertEqual(output[0][:3], (222, 223, 224))
        self.assertEqual(output[38][:3], (222, 223, 224))
        for y, x in ((0, 0), (15, 16), (31, 31), (0, 38), (17, 54), (31, 69)):
            panel_x = 6 + 16 + x if x < 32 else 76 + 16 + x - 38
            original = modified[(34 + 16 + y) * sheet_w + panel_x]
            self.assertEqual(output[y * width + x][:3], original)

    def test_cli_json_evidence_and_bad_landmark_failure(self):
        manifest = self.dir / "comparison.json"
        points = self.dir / "landmarks.json"
        manifest.write_text(json.dumps(self.manifest))
        points.write_text(json.dumps(self.landmarks))
        command = [sys.executable, str(ROOT / "forge/stage4_review/make_feature_crops.py"),
                   "--sheet", str(self.sheet), "--manifest", str(manifest),
                   "--landmarks-json", str(points), "--out", str(self.out),
                   "--roi", "0.25", "0.25", "0.75", "0.75", "--json"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["landmarkPairs"], 2)
        self.out.unlink()
        points.write_text(json.dumps(self.landmarks[:1]))
        bad = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("at least two", bad.stderr)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
