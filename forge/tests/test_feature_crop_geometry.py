"""No Pillow, browser, or user-supplied references required."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

STAGE = Path(__file__).resolve().parents[1] / "stage4_review"
sys.path.insert(0, str(STAGE))
from feature_crop_geometry import (  # noqa: E402
    combine_crops, crop_panel, fit_rect, panel_to_source, parse_features,
)
from make_feature_crops import create_feature_crops  # noqa: E402


class FeatureCropGeometryTest(unittest.TestCase):
    def sample_manifest(self):
        return {"schemaVersion": 1, "features": [
            {"id": "grip-ring", "referencePanelCenter": [0.5, 0.5], "renderPanelCenter": [0.6, 0.5]}
        ]}

    def test_explicit_independent_landmarks_are_required(self):
        self.assertEqual(len(parse_features(self.sample_manifest())), 1)
        for key in ("referencePanelCenter", "renderPanelCenter"):
            bad = self.sample_manifest()
            del bad["features"][0][key]
            with self.assertRaisesRegex(ValueError, key):
                parse_features(bad)

    def test_reject_unsafe_ids_duplicate_and_nonfinite_values(self):
        for invalid in ("../../etc/passwd", "/tmp/file", "foo.bar", "", "a" * 49):
            bad = self.sample_manifest()
            bad["features"][0]["id"] = invalid
            with self.assertRaises(ValueError):
                parse_features(bad)
        bad = self.sample_manifest()
        bad["features"].append(dict(bad["features"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_features(bad)
        for invalid in (float("nan"), float("inf"), False, -0.1, 1.1, "0.5"):
            bad = self.sample_manifest()
            bad["features"][0]["renderPanelCenter"][0] = invalid
            with self.assertRaisesRegex(ValueError, "renderPanelCenter"):
                parse_features(bad)

    def test_cover_matches_center_crop_exact_sampler(self):
        self.assertEqual(fit_rect(400, 100, 100, 100, "cover")[:4], (150, 0, 400, 100))
        self.assertEqual(panel_to_source([0, 0.5], 400, 100, 100, 100, "cover"), (150, 50))
        self.assertEqual(panel_to_source([1, 0.5], 400, 100, 100, 100, "cover"), (249, 50))

    def test_contain_letterbox_and_endpoints_are_exact(self):
        self.assertEqual(fit_rect(400, 100, 100, 100, "contain")[:4], (0, 37, 100, 25))
        self.assertIsNone(panel_to_source([0.5, 0], 400, 100, 100, 100, "contain"))
        self.assertEqual(panel_to_source([0, 0.5], 400, 100, 100, 100, "contain"), (0, 54))
        self.assertEqual(panel_to_source([1, 0.5], 400, 100, 100, 100, "contain"), (399, 54))

    def test_no_implicit_reprojection_or_resampling(self):
        pixels = [(x, y, 0) for y in range(16) for x in range(16)]
        centered = crop_panel(pixels, 16, 16, [8 / 15, 8 / 15], 4)
        shifted = crop_panel(pixels, 16, 16, [10 / 15, 8 / 15], 4)
        self.assertEqual(centered[0], (6, 6, 0))
        self.assertEqual(shifted[0], (8, 6, 0))
        w, h, together = combine_crops(centered, shifted, 4, 2)
        self.assertEqual((w, h), (10, 4))
        self.assertEqual(together[0], (6, 6, 0))
        self.assertEqual(together[6], (8, 6, 0))

    def test_refuse_out_of_panel_or_into_letterbox(self):
        pixels = [(1, 2, 3)] * 100
        with self.assertRaisesRegex(ValueError, "outside"):
            crop_panel(pixels, 10, 10, [0, 0], 4)
        with self.assertRaisesRegex(ValueError, "letterbox"):
            crop_panel(pixels, 10, 10, [.5, .5], 4, (0, 4, 10, 2))
        with self.assertRaisesRegex(ValueError, "pixel count"):
            crop_panel(pixels[:40], 10, 10, [.5, .5], 4)

    def test_cli_path_uses_sheet_scaler_dual_centers_and_safe_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "features.json"
            manifest.write_text(json.dumps(self.sample_manifest()), encoding="utf-8")
            saved = {}
            fake = types.SimpleNamespace(
                load_image=lambda path: (64, 64, [(0, 0, 0, 255)] * (64 * 64)),
                resize_cover=lambda w, h, rgba, tw, th: [(x, y, 0) for y in range(th) for x in range(tw)],
                write_png_rgb=lambda path, w, h, pixels: saved.update({path.name: (w, h, pixels[:1])}),
            )
            with patch.dict(sys.modules, {"make_comparison_sheet": fake}):
                report = create_feature_crops(root / "ref.png", root / "render.png", manifest, root / "out",
                                              panel_w=64, panel_h=64, crop_size=16)
            self.assertEqual(report["fit"], "cover")
            self.assertEqual(report["features"][0]["referenceSamplePixel"], (32, 32))
            self.assertEqual(report["features"][0]["renderSamplePixel"], (38, 32))
            self.assertEqual(saved["grip-ring.png"][0:2], (48, 16))
            self.assertTrue((root / "out" / "feature-crops.json").is_file())

    def test_manifest_rejects_bad_shapes_without_creating_artifacts(self):
        for bad in ({}, {"schemaVersion": 1, "features": []}, {"schemaVersion": True, "features": []},
                    {"schemaVersion": 1, "features": "not a list"}):
            with self.assertRaises(ValueError):
                parse_features(bad)

    def test_contain_mode_rejects_margins_before_writing_any_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "features.json"
            raw = self.sample_manifest()
            raw["features"][0]["referencePanelCenter"] = [0.5, 0.25]
            manifest.write_text(json.dumps(raw), encoding="utf-8")
            writes = []
            fake = types.SimpleNamespace(
                load_image=lambda path: (400, 100, [(0, 0, 0, 255)] * (400 * 100)),
                resize_contain=lambda w, h, rgba, tw, th: [(2, 3, 4)] * (tw * th),
                write_png_rgb=lambda *args: writes.append(args),
            )
            with patch.dict(sys.modules, {"make_comparison_sheet": fake}):
                with self.assertRaisesRegex(ValueError, "letterbox"):
                    create_feature_crops(root / "ref.png", root / "render.png", manifest, root / "out",
                                         panel_w=64, panel_h=64, crop_size=16)
            self.assertEqual(writes, [])
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
