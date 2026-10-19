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

    def test_unknown_neighborhood_is_refused(self) -> None:
        data = self.manifest("original")
        data["neighborhood"] = "unregistered"
        with self.assertRaisesRegex(RuntimeError, "unknown or altered candidate neighborhood"):
            self.score(data)


if __name__ == "__main__":
    unittest.main()
