"""Bound browser allocations before touching capture receipts."""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from forge.stage4_review.render_bridge import init_manifest, write_manifest
from forge.tests.test_render_bridge import write_png
from scripts.capture_threejs_playwright import _validated_runtime, capture


class CaptureRuntimePreflightTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.reference = self.root / "source.png"
        self.manifest_path = self.root / "manifest.json"
        write_png(self.reference)
        self.manifest = init_manifest(
            self.reference, "http://127.0.0.1:5173",
            self.manifest_path, (620, 1000), 1.0, "captures",
        )

    def assert_failed_before_side_effects(self, runtime, message):
        self.manifest["runtime"] = runtime
        write_manifest(self.manifest_path, self.manifest)
        before = self.manifest_path.read_bytes()
        with self.assertRaisesRegex(ValueError, message):
            capture(self.manifest_path, ["hero"], False, 100, "procedural")
        self.assertEqual(self.manifest_path.read_bytes(), before)
        self.assertFalse((self.root / "captures" / "hero.png").exists())

    def test_valid_viewports_preserve_original_semantics(self):
        self.assertEqual(_validated_runtime({"viewport": [620, 1000], "devicePixelRatio": 1}), ((620, 1000), 1.0))
        self.assertEqual(_validated_runtime({"viewport": [2560.0, 1440], "devicePixelRatio": 2}), ((2560, 1440), 2.0))
        self.assertEqual(_validated_runtime({}), ((620, 1000), 1.0))

    def test_viewport_structure_rejected_before_launch(self):
        for viewport in (None, [], [640], [640, 480, 100], "640x480", {"width": 640, "height": 480}):
            with self.subTest(value=viewport):
                self.assert_failed_before_side_effects(
                    {"url": "http://localhost", "viewport": viewport, "devicePixelRatio": 1},
                    "runtime.viewport",
                )

    def test_nonpositive_fractional_boolean_and_nonfinite_viewports(self):
        for bad in (0, -1, 1.2, True, None, "640", math.nan, math.inf, -math.inf, 10**1000):
            with self.subTest(value=str(bad)[:40]):
                self.assert_failed_before_side_effects(
                    {"url": "http://localhost", "viewport": [bad, 480], "devicePixelRatio": 1},
                    "runtime.viewport",
                )

    def test_dpr_invalid_inputs_fail_closed(self):
        for bad in (0, -1, -math.inf, math.inf, math.nan, True, None, "2", 10**1000, 9):
            with self.subTest(value=str(bad)[:40]):
                self.assert_failed_before_side_effects(
                    {"url": "http://localhost", "viewport": [640, 480], "devicePixelRatio": bad},
                    "runtime.devicePixelRatio",
                )

    def test_device_pixel_area_limit_prevents_unbounded_screenshots(self):
        self.assert_failed_before_side_effects(
            {"url": "http://localhost", "viewport": [8192, 8192], "devicePixelRatio": 1},
            "64 million device pixels",
        )
        self.assert_failed_before_side_effects(
            {"url": "http://localhost", "viewport": [4096, 4096], "devicePixelRatio": 2},
            "64 million device pixels",
        )
        self.assertEqual(_validated_runtime({"viewport": [4096, 4096], "devicePixelRatio": 1})[0], (4096, 4096))

    def test_invalid_runtime_object_has_clear_error(self):
        for value in (None, False, [], "oops"):
            with self.subTest(value=value):
                self.assert_failed_before_side_effects(value, "runtime must be an object")

    def test_missing_or_nonstring_runtime_url_fails_before_invalidation(self):
        for invalid in (None, False, 123, "", "   ", []):
            with self.subTest(url=invalid):
                self.assert_failed_before_side_effects(
                    {"url": invalid, "viewport": [640, 480], "devicePixelRatio": 1},
                    "runtime.url",
                )

    def test_invalid_dimensions_do_not_mutate_prior_complete_hero_receipt(self):
        hero = self.manifest["captures"][0]
        hero.update({
            "status": "recorded",
            "readySignal": True,
            "screenshotSha256": "f" * 64,
            "consoleErrors": [],
            "captureReceipt": {"version": 1, "complete": True, "inputSignature": "f" * 64},
        })
        self.assert_failed_before_side_effects(
            {"url": "http://localhost", "viewport": [0, 500], "devicePixelRatio": 1},
            "runtime.viewport",
        )


if __name__ == "__main__":
    unittest.main()
