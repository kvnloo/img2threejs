"""Capture output paths must never overwrite reference data or other evidence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from forge.stage4_review.render_bridge import init_manifest, write_manifest
from forge.tests.test_glb_reference import write_triangle_glb
from forge.tests.test_render_bridge import write_png
from scripts.capture_threejs_playwright import _validate_output_destinations, capture


PROFILE = Path(__file__).resolve().parents[2] / "docs/specs/render-profile.v2.example.json"


class CaptureOutputPathSafetyTest(unittest.TestCase):
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

    def preflight(self):
        _validate_output_destinations(self.manifest_path, self.manifest)

    def assert_rejected_before_browser(self, message):
        write_manifest(self.manifest_path, self.manifest)
        before = self.manifest_path.read_bytes()
        with self.assertRaisesRegex(ValueError, message):
            capture(self.manifest_path, ["hero"], False, 500, "procedural")
        self.assertEqual(self.manifest_path.read_bytes(), before)
        self.assertTrue(self.reference.is_file())

    def test_generated_distinct_paths_are_accepted(self):
        self.preflight()

    def test_reference_input_cannot_be_a_screenshot_destination(self):
        self.manifest["captures"][0]["path"] = "source.png"
        self.assert_rejected_before_browser("aliases protected reference")
        self.assertEqual(self.reference.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_capture_cannot_replace_the_manifest_itself(self):
        self.manifest["captures"][0]["path"] = str(self.manifest_path)
        self.assert_rejected_before_browser("aliases protected render manifest")

    def test_unselected_orbit_must_not_share_hero_output(self):
        hero, orbit = self.manifest["captures"][:2]
        orbit["path"] = hero["path"]
        self.assert_rejected_before_browser("output aliases procedural capture")

    def test_v2_diagnostic_pass_cannot_replace_source_or_other_pass(self):
        self.manifest = init_manifest(
            self.reference, "http://127.0.0.1:5173",
            self.manifest_path, (620, 1000), 1.0, "captures",
            render_profile=PROFILE,
        )
        depth = self.manifest["captures"][0]["passes"]["depth"]
        depth["path"] = str(self.reference)
        self.assert_rejected_before_browser("aliases protected reference")
        depth["path"] = self.manifest["captures"][0]["passes"]["normal"]["path"]
        self.assert_rejected_before_browser("output aliases")

    def test_v2_diagnostic_pass_cannot_overwrite_render_profile(self):
        self.manifest = init_manifest(
            self.reference, "http://127.0.0.1:5173",
            self.manifest_path, (620, 1000), 1.0, "captures",
            render_profile=PROFILE,
        )
        self.manifest["captures"][0]["passes"]["depth"]["path"] = str(PROFILE)
        self.assert_rejected_before_browser("aliases protected renderProfile")

    def test_glb_baseline_cannot_overwrite_source_or_procedural_shot(self):
        glb = self.root / "reference.glb"
        write_triangle_glb(glb)
        self.manifest = init_manifest(
            None, "http://127.0.0.1:5173",
            self.manifest_path, (620, 1000), 1.0, "captures",
            reference_glb=glb, reference_browser_url="/reference.glb",
        )
        self.reference = glb
        baseline = self.manifest["captures"][0]["reference"]
        baseline["path"] = str(glb)
        self.assert_rejected_before_browser("aliases protected reference")
        baseline["path"] = self.manifest["captures"][0]["path"]
        self.assert_rejected_before_browser("output aliases procedural capture")

    def test_resolved_symlink_alias_is_rejected(self):
        screenshot = self.root / "linked-screenshot.png"
        try:
            screenshot.symlink_to(self.reference)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.manifest["captures"][0]["path"] = str(screenshot)
        self.assert_rejected_before_browser("aliases protected reference")

    def test_distinct_external_output_path_is_allowed(self):
        other = self.root.parent / (self.root.name + "-external-output.png")
        self.manifest["captures"][0]["path"] = str(other)
        self.preflight()


if __name__ == "__main__":
    unittest.main()
