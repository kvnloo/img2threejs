"""Python capture helper defaults cannot invent readiness evidence."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forge.stage4_review.render_bridge import (
    init_manifest,
    record_capture,
    record_reference_capture,
    validate_manifest,
    write_manifest,
)
from forge.tests.test_render_bridge import write_png


class CaptureHelperReadinessDefaultsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.reference = self.root / "reference.png"
        self.screenshot = self.root / "shot.png"
        self.manifest_file = self.root / "manifest.json"
        write_png(self.reference)
        write_png(self.screenshot)
        self.manifest = init_manifest(
            self.reference, "http://127.0.0.1:5173",
            self.manifest_file, (620, 1000), 1.0, "captures"
        )

    def test_direct_helper_default_is_unverified_and_hashed(self):
        record = record_capture(
            self.manifest_file, self.manifest, "hero", self.screenshot
        )
        self.assertIsNone(record["readySignal"])
        self.assertEqual(record["status"], "recorded")
        self.assertEqual(len(record["screenshotSha256"]), 64)
        write_manifest(self.manifest_file, self.manifest)
        result = validate_manifest(self.manifest_file)
        self.assertFalse(result["passed"])
        self.assertTrue(any("ready signal" in e for e in result["errors"]))

    def test_direct_helper_explicit_true_still_valid(self):
        record_capture(
            self.manifest_file, self.manifest, "hero", self.screenshot,
            ready_signal=True,
        )
        write_manifest(self.manifest_file, self.manifest)
        self.assertTrue(validate_manifest(self.manifest_file)["passed"])

    def test_unverified_helper_re_record_replaces_prior_readiness(self):
        record_capture(
            self.manifest_file, self.manifest, "hero", self.screenshot,
            ready_signal=True,
        )
        record = record_capture(
            self.manifest_file, self.manifest, "hero", self.screenshot,
        )
        self.assertIsNone(record["readySignal"])
        write_manifest(self.manifest_file, self.manifest)
        self.assertFalse(validate_manifest(self.manifest_file)["passed"])

    def test_glb_baseline_default_is_unverified(self):
        self.manifest["reference"]["kind"] = "glb"
        self.manifest["captures"][0]["reference"] = {
            "status": "pending", "path": "reference/hero.png"
        }
        record = record_reference_capture(
            self.manifest_file, self.manifest, "hero", self.screenshot
        )
        self.assertIsNone(record["readySignal"])
        self.assertEqual(record["status"], "recorded")
        self.assertEqual(len(record["screenshotSha256"]), 64)
        with patch(
            "forge.stage4_review.render_bridge.probe_glb",
            return_value={"referenceReadiness": "pass"},
        ):
            write_manifest(self.manifest_file, self.manifest)
            result = validate_manifest(self.manifest_file)
        self.assertFalse(result["passed"])
        self.assertTrue(any(
            "GLB reference capture lacks a passing ready signal" in e
            for e in result["errors"]
        ))

    def test_glb_baseline_explicit_true_is_allowed(self):
        self.manifest["reference"]["kind"] = "glb"
        self.manifest["captures"][0]["reference"] = {
            "status": "pending", "path": "reference/hero.png"
        }
        record_reference_capture(
            self.manifest_file, self.manifest, "hero", self.screenshot,
            ready_signal=True,
        )
        with patch(
            "forge.stage4_review.render_bridge.probe_glb",
            return_value={"referenceReadiness": "pass"},
        ):
            write_manifest(self.manifest_file, self.manifest)
            result = validate_manifest(self.manifest_file)
        self.assertFalse(any("GLB reference capture lacks a passing ready signal" in e
                             for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
