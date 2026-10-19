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
