"""Fail-fast manifest integrity checks for real-browser fitting cohorts.

Run in the ordinary pure-stdlib Python suite so obvious cohort/variable
regressions fail before expensive Chrome rendering is scheduled.
"""
from __future__ import annotations

import importlib.util
from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "experiments" / "dream_rsi_mesh_fidelity" / "real_render_smoke.py"
SPEC = importlib.util.spec_from_file_location("rsi_real_render_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
rsi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rsi)


class RealBrowserCohortIntegrityTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def manifest(self, neighborhood: str) -> dict:
        return {
            "status": "prepared-not-rendered",
            "fixtureSha256": rsi.sha256(rsi.FIXTURE),
            "neighborhood": neighborhood,
            "parameters": deepcopy(rsi.NEIGHBORHOODS[neighborhood]),
            "variants": [{"name": name} for name in rsi.NEIGHBORHOODS[neighborhood]],
        }

    def score(self, data: dict) -> None:
        (self.root / "manifest.json").write_text(
            json.dumps(data), encoding="utf-8",
        )
        rsi.score(self.root)

    def test_original_and_calibrated_cohorts_pass_manifest_check(self) -> None:
        # No real browser files are present: valid manifests must reach the
        # expected missing-image boundary, rather than raising NameError.
        for neighborhood in ("original", "calibrated"):
            with self.subTest(neighborhood=neighborhood):
                with self.assertRaisesRegex(RuntimeError, "missing true browser-rendered target"):
                    self.score(self.manifest(neighborhood))

    def test_missing_or_reordered_candidates_are_refused(self) -> None:
        for neighborhood in ("original", "calibrated"):
            for mode in ("missing", "reversed"):
                with self.subTest(neighborhood=neighborhood, mode=mode):
                    data = self.manifest(neighborhood)
                    if mode == "missing":
                        data["variants"].pop()
                    else:
                        data["variants"].reverse()
                    with self.assertRaisesRegex(RuntimeError, "candidate list drifted"):
                        self.score(data)

    def test_changed_cohort_vectors_are_refused(self) -> None:
        for neighborhood in ("original", "calibrated"):
            with self.subTest(neighborhood=neighborhood):
                data = self.manifest(neighborhood)
                data["parameters"]["root"][0] += 0.01
                with self.assertRaisesRegex(RuntimeError, "unknown or altered candidate neighborhood"):
                    self.score(data)

    def test_valid_webgl2_receipt_is_admitted_without_browser(self) -> None:
        folder = self.root / "root"
        folder.mkdir()
        (folder / "browser.json").write_text(json.dumps({
            "ready": True, "coverage": 0.25,
            "webgl": "WebGL 2.0 (OpenGL ES 3.0 Chromium)",
            "renderer": "WebKit WebGL", "chromium": "155.0.0",
            "errors": [],
        }), encoding="utf-8")
        rsi.verify_browser_receipt(folder, "root")

    def test_missing_bad_and_failed_capture_receipts_are_refused(self) -> None:
        folder = self.root / "root"
        folder.mkdir()
        receipt_file = folder / "browser.json"
        with self.assertRaisesRegex(RuntimeError, "missing or malformed"):
            rsi.verify_browser_receipt(folder, "root")
        receipt_file.write_text("{bad", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "missing or malformed"):
            rsi.verify_browser_receipt(folder, "root")

        valid = {
            "ready": True, "coverage": 0.25,
            "webgl": "WebGL 2.0 (OpenGL ES 3.0 Chromium)",
            "renderer": "WebKit WebGL", "chromium": "155.0.0",
            "errors": [],
        }
        variants = [
            ("ready", "true"), ("ready", 1), ("ready", False),
            ("errors", ["SECRET_SESSION_URL"]), ("errors", None),
            ("coverage", 0), ("coverage", 1), ("coverage", True),
            ("coverage", float("nan")), ("webgl", "WebGL 1.0"),
            ("renderer", ""), ("chromium", ""),
        ]
        for key, changed in variants:
            with self.subTest(field=key, value=changed):
                candidate = dict(valid)
                candidate[key] = changed
                receipt_file.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "unverified WebGL2") as error:
                    rsi.verify_browser_receipt(folder, "root")
                self.assertNotIn("SECRET_SESSION_URL", str(error.exception))

    def test_saved_spec_hash_must_match_prepared_manifest(self) -> None:
        manifest = self.manifest("original")
        for variant in manifest["variants"]:
            variant["specSha256"] = "f" * 64
            variant["generatedTypeScriptSha256"] = "e" * 64
        (self.root / "target").mkdir()
        (self.root / "target" / "spec.json").write_text("modified spec", encoding="utf-8")
        (self.root / "target" / "render.png").write_bytes(b"present")
        with self.assertRaisesRegex(RuntimeError, "frozen source spec changed"):
            self.score(manifest)

    def test_unknown_neighborhood_is_refused(self) -> None:
        data = self.manifest("original")
        data["neighborhood"] = "unregistered"
        with self.assertRaisesRegex(RuntimeError, "unknown or altered candidate neighborhood"):
            self.score(data)


if __name__ == "__main__":
    unittest.main()
