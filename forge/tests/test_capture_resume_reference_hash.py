"""Reference provenance gates for resumable browser capture planning."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage4_review"))
from make_comparison_sheet import write_png_rgb  # noqa: E402
from plan_capture_resume import resume_plan  # noqa: E402
from render_bridge import init_manifest, write_manifest  # noqa: E402


class CaptureResumeReferenceHashTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.ref = self.folder / "reference.png"
        write_png_rgb(self.ref, 2, 2, [(50, 50, 50)] * 4)
        self.manifest = self.folder / "manifest.json"
        self.data = init_manifest(
            self.ref, "http://localhost:3000/", self.manifest,
            (620, 1000), 1.0, "captures",
        )
        write_manifest(self.manifest, self.data)

    def test_unchanged_reference_allows_resumption(self):
        self.assertEqual(resume_plan(self.manifest)["requiredShots"], 7)

    def test_changed_reference_rejects_old_screenshot_receipts(self):
        self.ref.write_bytes(self.ref.read_bytes() + b"modified")
        with self.assertRaisesRegex(ValueError, "source reference hash changed"):
            resume_plan(self.manifest)

    def test_missing_source_hash_does_not_allow_resume(self):
        self.data["reference"].pop("sha256")
        write_manifest(self.manifest, self.data)
        with self.assertRaisesRegex(ValueError, "SHA-256 are required"):
            resume_plan(self.manifest)


if __name__ == "__main__":
    unittest.main()
