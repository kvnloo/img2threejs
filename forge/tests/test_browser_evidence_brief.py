"""Browser evidence summaries are compact but never substitute for evidence gates."""
from __future__ import annotations

import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage4_review"))

from browser_evidence_brief import build_brief, main  # noqa: E402
from render_bridge import init_manifest, record_capture, write_manifest  # noqa: E402


def png(width: int = 2, height: int = 2) -> bytes:
    """Build a valid RGBA PNG without PIL or a browser dependency."""
    def chunk(name: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload)) + name + payload
            + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)
        )
    data = b"".join(b"\x00" + b"\x90\x10\x50\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(data))
        + chunk(b"IEND", b"")
    )


class BrowserBriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reference = self.root / "reference.png"
        self.reference.write_bytes(png())
        self.shot = self.root / "hero.png"
        self.shot.write_bytes(png(3, 3))
        self.path = self.root / "manifest.json"
        self.manifest = init_manifest(
            self.reference, "http://127.0.0.1:5173/#/demo",
            self.path, (620, 1000), 1.0, "captures"
        )
        # A single-camera batch keeps the real manifest/validator test minimal.
        self.manifest["captures"] = self.manifest["captures"][:1]
        write_manifest(self.path, self.manifest)

    def record(self):
        record_capture(self.path, self.manifest, "hero", self.shot, ready_signal=True)
        write_manifest(self.path, self.manifest)

    def test_pending_manifest_never_claims_complete_evidence(self):
        brief = build_brief(self.path)
        self.assertFalse(brief["evidenceComplete"])
        self.assertEqual(brief["capturesRecorded"], 0)
        self.assertEqual(brief["pendingIds"], ["hero"])
        self.assertEqual(brief["nextStep"], "capture-missing")
        self.assertEqual(brief["visualAcceptance"], "not-assessed")

    def test_invalid_source_evidence_blocks_capture_before_more_views(self):
        # A missing orbit is not the next useful action when the source image
        # no longer matches the manifest's declared content digest.
        self.manifest["reference"]["sha256"] = "0" * 64
        write_manifest(self.path, self.manifest)
        brief = build_brief(self.path)
        self.assertFalse(brief["evidenceComplete"])
        self.assertGreater(brief["pendingCount"], 0)
        self.assertIn("failed-manifest-validation", brief["errorCategories"])
        self.assertEqual(brief["nextStep"], "repair-evidence")

    def test_unready_recorded_hero_blocks_more_captures(self):
        self.record()
        self.manifest["captures"][0]["readySignal"] = "true"
        write_manifest(self.path, self.manifest)
        brief = build_brief(self.path)
        self.assertIn("missing-readiness", brief["errorCategories"])
        self.assertGreater(brief["pendingCount"], 0)
        self.assertEqual(brief["nextStep"], "repair-evidence")

    def test_real_manifest_validation_and_verified_reuse(self):
        self.record()
        brief = build_brief(self.path)
        self.assertTrue(brief["evidenceComplete"], brief)
        self.assertEqual(brief["validationErrorCount"], 0)
        cached = build_brief(self.path, since=brief["digest"])
        self.assertEqual(cached["unchanged"], True)
        self.assertEqual(cached["visualAcceptance"], "not-assessed")
        self.assertLess(len(json.dumps(cached)), len(json.dumps(brief)))

    def test_changed_png_is_revalidated_despite_matching_manifest_digest(self):
        self.record()
        digest = build_brief(self.path)["digest"]
        self.shot.write_bytes(png(4, 3))
        brief = build_brief(self.path, since=digest)
        self.assertFalse(brief["evidenceComplete"])
        self.assertGreater(brief["validationErrorCount"], 0)
        self.assertNotIn("unchanged", brief)

    def test_missing_hash_and_non_boolean_readiness_fail_closed(self):
        self.record()
        item = self.manifest["captures"][0]
        item.pop("screenshotSha256")
        item["readySignal"] = 1
        write_manifest(self.path, self.manifest)
        brief = build_brief(self.path)
        self.assertFalse(brief["evidenceComplete"])
        self.assertIn("missing-readiness", brief["errorCategories"])
        self.assertIn("missing-capture-hash", brief["errorCategories"])

    def test_browser_console_secrets_and_dom_never_enter_output(self):
        self.record()
        secret = "PRIVATE_BROWSER_CONTEXT_DO_NOT_SHARE"
        self.manifest["captures"][0]["consoleErrors"] = [secret]
        self.manifest["captures"][0]["browserSnapshot"] = {
            "dom": secret + "x" * 100_000,
            "url": "https://secret.example/private",
        }
        self.manifest["evidence"]["consoleErrors"] = [secret]
        write_manifest(self.path, self.manifest)
        brief = build_brief(self.path)
        compact = json.dumps(brief)
        self.assertNotIn(secret, compact)
        self.assertNotIn("secret.example", compact)
        self.assertIn("browser-error", brief["errorCategories"])
        self.assertLess(len(compact) * 20, self.path.stat().st_size)

    def test_malformed_reference_and_duplicate_capture_never_pass(self):
        self.record()
        self.manifest["reference"]["sha256"] = ""
        self.manifest["captures"].append(dict(self.manifest["captures"][0]))
        write_manifest(self.path, self.manifest)
        brief = build_brief(self.path)
        self.assertFalse(brief["evidenceComplete"])
        self.assertIn("unverified-reference", brief["errorCategories"])
        self.assertIn("duplicate-capture", brief["errorCategories"])

    def test_unsafe_identifiers_are_redacted_without_fake_duplicate_errors(self):
        # Two distinct URLs can have the same truncated/sanitized prefix.
        # Display their positions, not parts of hostnames, paths or tokens.
        first = self.manifest["captures"][0]
        first["id"] = "https://secret.example/private/alpha?token=SENSITIVE"
        second = dict(first)
        second["id"] = "https://secret.example/private/beta?token=DIFFERENT"
        self.manifest["captures"].append(second)
        write_manifest(self.path, self.manifest)
        brief = build_brief(self.path)
        rendered = json.dumps(brief)
        self.assertEqual(brief["pendingIds"], ["capture-0", "capture-1"])
        self.assertNotIn("secret", rendered)
        self.assertNotIn("token", rendered)
        self.assertNotIn("duplicate-capture", brief["errorCategories"])

        # Real duplicates must still be detected using raw identity, not aliases.
        second["id"] = first["id"]
        write_manifest(self.path, self.manifest)
        brief = build_brief(self.path)
        self.assertIn("duplicate-capture", brief["errorCategories"])

    def test_nonstring_and_long_ids_never_crash_or_leak(self):
        first = self.manifest["captures"][0]
        for raw in (["untrusted"], {"token": "SECRET"}, "A" * 96):
            with self.subTest(raw_type=type(raw).__name__):
                first["id"] = raw
                write_manifest(self.path, self.manifest)
                brief = build_brief(self.path)
                self.assertFalse(brief["evidenceComplete"])
                self.assertEqual(brief["pendingIds"], ["capture-0"])
                self.assertNotIn("SECRET", json.dumps(brief))

    def test_cli_exit_codes_and_bounded_ids(self):
        args = ["--manifest", str(self.path), "--strict"]
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(args), 1)
        self.assertFalse(json.loads(out.getvalue())["evidenceComplete"])
        self.record()
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(args), 0)
        self.assertTrue(json.loads(out.getvalue())["evidenceComplete"])
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(["--manifest", str(self.root / "absent.json")]), 2)
        self.assertNotIn(str(self.root), err.getvalue())


if __name__ == "__main__":
    unittest.main()
