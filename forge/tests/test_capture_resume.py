"""Regression tests for read-only per-view capture resumption (#165)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage4_review"))
from make_comparison_sheet import write_png_rgb  # noqa: E402
from plan_capture_resume import resume_plan  # noqa: E402
from render_bridge import (  # noqa: E402
    init_manifest, read_manifest, record_capture, record_reference_capture,
    write_manifest,
)


class CaptureResumeTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.ref = self.folder / "reference.png"
        self.hero = self.folder / "hero.png"
        write_png_rgb(self.ref, 4, 4, [(40, 100, 160)] * 16)
        write_png_rgb(self.hero, 4, 4, [(160, 100, 40)] * 16)
        self.path = self.folder / "manifest.json"
        self.manifest = init_manifest(
            self.ref, "http://localhost:3000/", self.path,
            (620, 1000), 1.0, "captures",
        )
        write_manifest(self.path, self.manifest)

    def record_hero(self, ready=True, errors=None):
        record_capture(self.path, self.manifest, "hero", self.hero, ready, errors or [])
        write_manifest(self.path, self.manifest)

    def test_initial_plan_is_complete_and_read_only(self):
        before = self.path.read_bytes()
        plan = resume_plan(self.path)
        self.assertEqual(plan["verifiedShots"], 0)
        self.assertEqual(plan["requiredShots"], 7)
        self.assertEqual(plan["next"]["captureId"], "hero")
        self.assertEqual(plan["next"]["reason"], "not-recorded")
        self.assertFalse(plan["captureShotsComplete"])
        self.assertFalse(plan["fullReviewPassed"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_recorded_ready_hashed_hero_is_skipped(self):
        self.record_hero()
        before = self.path.read_bytes()
        plan = resume_plan(self.path)
        self.assertEqual(plan["verifiedShots"], 1)
        self.assertEqual(plan["next"]["captureId"], "orbit-plus35")
        self.assertEqual(len(plan["remaining"]), 6)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unready_console_error_and_changed_hash_requeue_hero(self):
        self.record_hero()
        self.manifest["captures"][0]["readySignal"] = "false"
        write_manifest(self.path, self.manifest)
        self.assertEqual(resume_plan(self.path)["next"]["reason"], "not-ready")
        self.manifest["captures"][0]["readySignal"] = True
        self.manifest["captures"][0]["consoleErrors"] = ["browser exception"]
        write_manifest(self.path, self.manifest)
        self.assertEqual(resume_plan(self.path)["next"]["reason"], "console-errors-or-unverified")
        self.manifest["captures"][0]["consoleErrors"] = []
        write_manifest(self.path, self.manifest)
        self.hero.write_bytes(self.hero.read_bytes() + b"x")
        self.assertEqual(resume_plan(self.path)["next"]["reason"], "changed-screenshot")

    def test_glb_queues_reference_baseline_first_but_preserves_good_shots(self):
        self.manifest["reference"]["kind"] = "glb"
        for capture in self.manifest["captures"]:
            capture["reference"] = {"status": "pending", "path": f"reference/{capture['id']}.png"}
        self.record_hero()
        plan = resume_plan(self.path)
        self.assertEqual(plan["requiredShots"], 14)
        self.assertEqual(plan["verifiedShots"], 1)
        self.assertEqual(plan["next"]["captureId"], "hero")
        self.assertEqual(plan["next"]["mode"], "reference")
        record_reference_capture(self.path, self.manifest, "hero", self.ref, True, [])
        write_manifest(self.path, self.manifest)
        next_plan = resume_plan(self.path)
        self.assertEqual(next_plan["verifiedShots"], 2)
        self.assertEqual(next_plan["next"]["captureId"], "orbit-plus35")
        self.assertEqual(next_plan["next"]["mode"], "reference")

    def test_duplicate_ids_fail_and_cli_reports_errors_without_writing(self):
        self.manifest["captures"].append(dict(self.manifest["captures"][0]))
        write_manifest(self.path, self.manifest)
        with self.assertRaisesRegex(ValueError, "duplicate capture"):
            resume_plan(self.path)
        before = self.path.read_bytes()
        result = subprocess.run(
            [sys.executable, str(ROOT / "forge/stage4_review/plan_capture_resume.py"),
             "--manifest", str(self.path)],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate capture", result.stderr)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
