"""The compact browser brief must require all v2 render evidence, not only a beauty PNG."""

from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

STAGE4 = Path(__file__).resolve().parents[1] / "stage4_review"
sys.path.insert(0, str(STAGE4))

from forge.stage4_review.browser_evidence_brief import build_brief
from forge.stage4_review.render_bridge import (
    init_manifest,
    record_capture,
    record_capture_pass,
    write_manifest,
)
from forge.stage4_review.multi_pass import PASS_IDS
from forge.tests.test_render_bridge import write_png


PROFILE = Path(__file__).resolve().parents[2] / "docs/specs/render-profile.v2.example.json"


class BrowserBriefV2EvidenceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.reference = self.root / "source.png"
        self.shot = self.root / "hero.png"
        self.manifest_path = self.root / "render-manifest.json"
        write_png(self.reference)
        write_png(self.shot)
        self.manifest = init_manifest(
            self.reference, "http://127.0.0.1:5173", self.manifest_path,
            (620, 1000), 1.0, "captures", render_profile=PROFILE,
        )
        self.manifest["captures"] = self.manifest["captures"][:1]
        record_capture(
            self.manifest_path, self.manifest, "hero", self.shot,
            ready_signal=True, console_errors=[],
        )
        self.save()

    def save(self):
        write_manifest(self.manifest_path, self.manifest)

    def record_pass(self, pass_id):
        record_capture_pass(
            self.manifest_path, self.manifest, "hero", pass_id, self.shot,
        )
        self.save()

    def assert_needs_repair(self, category):
        result = build_brief(self.manifest_path)
        self.assertFalse(result["evidenceComplete"], result)
        self.assertEqual(result["nextStep"], "repair-evidence")
        self.assertIn(category, result["errorCategories"])
        return result

    def test_one_recorded_pass_must_not_claim_full_evidence(self):
        self.record_pass("beauty")
        result = self.assert_needs_repair("missing-diagnostic-passes")
        self.assertEqual(result["capturesRecorded"], 1)
        self.assertEqual(result["pendingCount"], 0)
        self.assertEqual(result["repairCount"], 1)

    def test_extra_nonstandard_recorded_pass_cannot_replace_required_pass(self):
        self.record_pass("beauty")
        self.manifest["captures"][0]["passes"]["unrelated"] = {
            "status": "recorded", "path": "not-a-true-required-pass.png",
        }
        self.save()
        self.assert_needs_repair("missing-diagnostic-passes")

    def test_all_six_healthy_passes_can_report_evidence_ready(self):
        for pid in PASS_IDS:
            self.record_pass(pid)
        result = build_brief(self.manifest_path)
        self.assertEqual(result["errorCategories"], [], result)
        self.assertTrue(result["evidenceComplete"], result)
        self.assertEqual(result["nextStep"], "visual-review")
        self.assertEqual(result["visualAcceptance"], "not-assessed")
        cached = build_brief(self.manifest_path, since=result["digest"])
        self.assertTrue(cached.get("unchanged"))

    def test_missing_sha_or_image_metadata_cannot_be_reused(self):
        for pid in PASS_IDS:
            self.record_pass(pid)
        record = self.manifest["captures"][0]["passes"]["depth"]
        record.pop("sha256")
        self.save()
        self.assert_needs_repair("missing-diagnostic-passes")
        record["sha256"] = "0" * 64
        record.pop("image")
        self.save()
        self.assert_needs_repair("missing-diagnostic-passes")

    def test_absent_clean_browser_receipt_is_not_verified(self):
        for pid in PASS_IDS:
            self.record_pass(pid)
        self.manifest["captures"][0].pop("consoleErrors")
        self.save()
        self.assert_needs_repair("unverified-browser-errors")

    def test_error_receipts_remain_browser_error_category(self):
        for pid in PASS_IDS:
            self.record_pass(pid)
        self.manifest["captures"][0]["consoleErrors"] = ["simulated console failure"]
        self.save()
        self.assert_needs_repair("browser-error")


if __name__ == "__main__":
    unittest.main()
