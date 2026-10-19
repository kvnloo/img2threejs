"""A saved PNG is evidence of bytes, not evidence that the browser became ready."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forge.stage4_review.render_bridge import (
    diagnose,
    init_manifest,
    ready_signal_passed,
    record_capture,
    validate_manifest,
    write_manifest,
)
from forge.tests.test_render_bridge import write_png


class RenderReadySignalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.reference = self.root / "source.png"
        self.screenshot = self.root / "capture.png"
        self.manifest_path = self.root / "manifest.json"
        write_png(self.reference)
        write_png(self.screenshot)
        self.manifest = init_manifest(
            self.reference, "http://127.0.0.1:5173", self.manifest_path,
            (620, 1000), 1.0, "captures",
        )

    def test_browser_adapter_waits_for_explicit_boolean_true(self):
        adapter = Path(__file__).resolve().parents[2] / "scripts" / "capture_threejs_playwright.py"
        source = adapter.read_text(encoding="utf-8")
        self.assertIn("window.__IMG2THREEJS_READY__ === true", source)
        self.assertNotIn("Boolean(window.__IMG2THREEJS_READY__)", source)

    def test_only_explicit_true_proves_browser_readiness(self):
        for signal in (True, "true", " TRUE "):
            self.assertTrue(ready_signal_passed(signal))
        for signal in (False, None, "false", "1", 1, "yes", {}, []):
            self.assertFalse(ready_signal_passed(signal))

    def test_unready_record_is_hashed_but_fails_validation(self):
        for signal in (False, "false", None, "yes", 1):
            with self.subTest(signal=signal):
                self.manifest = init_manifest(
                    self.reference, "http://127.0.0.1:5173", self.manifest_path,
                    (620, 1000), 1.0, "captures",
                )
                record = record_capture(self.manifest_path, self.manifest, "hero", self.screenshot, signal)
                self.assertEqual(record["status"], "recorded")
                self.assertEqual(len(record["screenshotSha256"]), 64)
                write_manifest(self.manifest_path, self.manifest)
                result = validate_manifest(self.manifest_path)
                self.assertFalse(result["passed"])
                self.assertTrue(any("ready signal" in error for error in result["errors"]))

    def test_valid_boolean_or_cli_text_ready_signal_still_passes(self):
        for signal in (True, "true", " TRUE "):
            with self.subTest(signal=signal):
                self.manifest = init_manifest(
                    self.reference, "http://127.0.0.1:5173", self.manifest_path,
                    (620, 1000), 1.0, "captures",
                )
                record_capture(self.manifest_path, self.manifest, "hero", self.screenshot, signal)
                write_manifest(self.manifest_path, self.manifest)
                self.assertTrue(validate_manifest(self.manifest_path)["passed"])

    def test_missing_readiness_on_legacy_record_must_not_pass(self):
        record = record_capture(self.manifest_path, self.manifest, "hero", self.screenshot)
        del record["readySignal"]
        write_manifest(self.manifest_path, self.manifest)
        self.assertFalse(validate_manifest(self.manifest_path)["passed"])

    def test_invalid_reference_is_reported_instead_of_crashing(self):
        self.manifest["reference"] = None
        write_manifest(self.manifest_path, self.manifest)
        result = validate_manifest(self.manifest_path)
        self.assertFalse(result["passed"])
        self.assertIn("reference.path is required", result["errors"])

    def test_glb_baseline_with_missing_path_or_false_readiness_fails(self):
        self.manifest["reference"]["kind"] = "glb"
        hero = self.manifest["captures"][0]
        hero["reference"] = {"status": "recorded", "readySignal": True}
        with patch("forge.stage4_review.render_bridge.probe_glb", return_value={"referenceReadiness": "pass"}):
            write_manifest(self.manifest_path, self.manifest)
            result = validate_manifest(self.manifest_path)
            self.assertTrue(any("baseline has no path" in error for error in result["errors"]))
            hero["reference"]["path"] = "source.png"
            hero["reference"]["readySignal"] = False
            write_manifest(self.manifest_path, self.manifest)
            result = validate_manifest(self.manifest_path)
            self.assertTrue(any("GLB reference capture lacks a passing ready signal" in error for error in result["errors"]))

    def test_diagnostics_refuse_unready_hero_and_orbit(self):
        record_capture(self.manifest_path, self.manifest, "hero", self.screenshot, False)
        write_manifest(self.manifest_path, self.manifest)
        with self.assertRaisesRegex(ValueError, "hero capture must have a passing"):
            diagnose(self.manifest_path, self.root / "report.json")
        record_capture(self.manifest_path, self.manifest, "hero", self.screenshot, True)
        record_capture(self.manifest_path, self.manifest, "orbit-plus35", self.screenshot, "false")
        write_manifest(self.manifest_path, self.manifest)
        with self.assertRaisesRegex(ValueError, "orbit capture lacks a passing"):
            diagnose(self.manifest_path, self.root / "report.json")
        self.assertFalse((self.root / "report.json").exists())

    def test_cli_omitted_ready_signal_does_not_pass_validation(self):
        write_manifest(self.manifest_path, self.manifest)
        script = Path(__file__).resolve().parents[1] / "stage4_review" / "render_bridge.py"
        cmd = [sys.executable, str(script)]
        recorded = subprocess.run(cmd + [
            "record", "--manifest", str(self.manifest_path), "--capture-id", "hero",
            "--screenshot", str(self.screenshot),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        validated = subprocess.run(cmd + [
            "validate", "--manifest", str(self.manifest_path),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(validated.returncode, 1, validated.stderr)
        self.assertIn("ready signal", validated.stdout)

    def test_cli_false_text_does_not_succeed_on_validate(self):
        write_manifest(self.manifest_path, self.manifest)
        script = Path(__file__).resolve().parents[1] / "stage4_review" / "render_bridge.py"
        command = [sys.executable, str(script)]
        recorded = subprocess.run(command + [
            "record", "--manifest", str(self.manifest_path), "--capture-id", "hero",
            "--screenshot", str(self.screenshot), "--ready-signal", "false",
        ], capture_output=True, text=True, check=False)
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        validated = subprocess.run(command + [
            "validate", "--manifest", str(self.manifest_path),
        ], capture_output=True, text=True, check=False)
        self.assertEqual(validated.returncode, 1, validated.stderr)
        self.assertIn("ready signal", validated.stdout)


if __name__ == "__main__":
    unittest.main()
