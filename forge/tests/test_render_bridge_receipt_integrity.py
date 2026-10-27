"""Recorded browser evidence requires a hash and an explicit clean console receipt."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from forge.stage4_review.render_bridge import (
    diagnose, init_manifest, record_capture, record_reference_capture,
    validate_manifest, write_manifest,
)
from forge.tests.test_glb_reference import write_triangle_glb
from forge.tests.test_render_bridge import write_png


class RecordedCaptureReceiptTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.reference = self.root / "reference.png"
        self.image = self.root / "shot.png"
        self.path = self.root / "manifest.json"
        write_png(self.reference)
        write_png(self.image)
        self.manifest = init_manifest(
            self.reference, "http://127.0.0.1:5173",
            self.path, (620, 1000), 1.0, "captures",
        )
        record_capture(self.path, self.manifest, "hero", self.image, ready_signal=True)
        write_manifest(self.path, self.manifest)

    def validate(self):
        write_manifest(self.path, self.manifest)
        return validate_manifest(self.path)

    def test_explicit_hasher_and_empty_console_baseline_is_valid(self):
        self.assertTrue(self.validate()["passed"])

    def test_missing_capture_hash_never_passes_validation_or_diagnostics(self):
        capture = self.manifest["captures"][0]
        capture.pop("screenshotSha256")
        result = self.validate()
        self.assertFalse(result["passed"])
        self.assertTrue(any("no valid SHA-256" in e for e in result["errors"]))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            diagnose(self.path, self.root / "diagnostic.json")
        self.assertFalse((self.root / "diagnostic.json").exists())

    def test_malformed_capture_hash_fails_even_with_intact_png(self):
        capture = self.manifest["captures"][0]
        for bad in (None, "0" * 63, "g" * 64, "A" * 64):
            with self.subTest(hash=bad):
                capture["screenshotSha256"] = bad
                self.assertFalse(self.validate()["passed"])

    def test_missing_capture_console_receipt_is_not_clean(self):
        self.manifest["captures"][0].pop("consoleErrors")
        result = self.validate()
        self.assertFalse(result["passed"])
        self.assertTrue(any("unverified console receipt" in e for e in result["errors"]))

    def test_glb_reference_baseline_needs_a_hash_and_console_receipt(self):
        glb = self.root / "reference.glb"
        write_triangle_glb(glb)
        self.manifest = init_manifest(
            None, "http://127.0.0.1:5173", self.path, (620, 1000), 1.0,
            "captures", reference_glb=glb,
        )
        record_reference_capture(
            self.path, self.manifest, "hero", self.image, ready_signal=True,
        )
        record_capture(
            self.path, self.manifest, "hero", self.image, ready_signal=True,
        )
        self.assertTrue(self.validate()["passed"])
        baseline = self.manifest["captures"][0]["reference"]
        baseline.pop("screenshotSha256")
        self.assertTrue(any("no valid SHA-256" in e for e in self.validate()["errors"]))
        baseline["screenshotSha256"] = "0" * 64
        baseline.pop("consoleErrors")
        result = self.validate()
        self.assertTrue(any("unverified console receipt" in e for e in result["errors"]))
        self.assertTrue(any("hash changed" in e for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
