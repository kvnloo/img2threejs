"""Only repository-owned camera labels may leave a browser evidence manifest."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage4_review"))

from browser_evidence_brief import build_brief, main  # noqa: E402
from make_comparison_sheet import write_png_rgb  # noqa: E402
from render_bridge import init_manifest, write_manifest  # noqa: E402


class BrowserBriefCaptureIdPrivacyTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        reference = self.root / "reference.png"
        write_png_rgb(reference, 2, 2, [(10, 20, 30)] * 4)
        self.manifest_file = self.root / "manifest.json"
        self.manifest = init_manifest(
            reference, "http://127.0.0.1:5173/#/subject",
            self.manifest_file, (620, 1000), 1.0, "captures",
        )
        self.manifest["captures"] = self.manifest["captures"][:2]

    def brief(self):
        write_manifest(self.manifest_file, self.manifest)
        return build_brief(self.manifest_file)

    def test_canonical_camera_names_remain_actionable(self):
        result = self.brief()
        self.assertEqual(result["pendingIds"], ["hero", "orbit-plus35"])

    def test_safe_looking_secret_slugs_are_never_displayed(self):
        for raw_id in (
            "sk_live_ABC123456789",
            "Authorization_Bearer_PRIVATE",
            "apiKey.supersecret",
            "user.name_private",
            "token987654321",
            "valid_ascii_label",
        ):
            with self.subTest(raw_id=raw_id):
                self.manifest["captures"][0]["id"] = raw_id
                result = self.brief()
                self.assertEqual(result["pendingIds"], ["capture-0", "orbit-plus35"])
                self.assertNotIn(raw_id, json.dumps(result, ensure_ascii=False))

    def test_recorded_invalid_capture_never_echoes_secret_on_repair(self):
        private_id = "BearerSecretStoredInCaptureId"
        shot = self.root / "shot.png"
        write_png_rgb(shot, 3, 3, [(40, 50, 60)] * 9)
        capture = self.manifest["captures"][0]
        capture.update({
            "id": private_id,
            "path": str(shot),
            "status": "recorded",
            "readySignal": "false",
            "consoleErrors": [],
        })
        result = self.brief()
        self.assertFalse(result["evidenceComplete"])
        self.assertEqual(result["repairIds"], ["capture-0"])
        self.assertNotIn(private_id, json.dumps(result))

    def test_duplicate_raw_secret_ids_are_detected_without_echo(self):
        secret = "SecretSameTokenValue"
        for capture in self.manifest["captures"]:
            capture["id"] = secret
        result = self.brief()
        self.assertIn("duplicate-capture", result["errorCategories"])
        self.assertEqual(result["pendingIds"], ["capture-0", "capture-1"])
        self.assertNotIn(secret, json.dumps(result))

    def test_malformed_reference_fails_with_generic_error_not_traceback(self):
        self.manifest["reference"] = None
        self.brief_file = self.manifest_file
        write_manifest(self.brief_file, self.manifest)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["--manifest", str(self.brief_file)])
        self.assertEqual(code, 2)
        self.assertIn("browser brief: AttributeError", stderr.getvalue())
        self.assertNotIn(str(self.root), stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_distinct_raw_secrets_do_not_collide_after_redaction(self):
        self.manifest["captures"][0]["id"] = "S3cretUniqueAlpha"
        self.manifest["captures"][1]["id"] = "S3cretUniqueBeta"
        result = self.brief()
        self.assertNotIn("duplicate-capture", result["errorCategories"])
        self.assertEqual(result["pendingIds"], ["capture-0", "capture-1"])


if __name__ == "__main__":
    unittest.main()
