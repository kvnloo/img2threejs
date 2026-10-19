"""On-demand Chromium fitting: verify cohort provenance and dispatch without Chrome."""
from __future__ import annotations

import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "experiments" / "dream_rsi_mesh_fidelity" / "live_budget_ab.py"
SPEC = importlib.util.spec_from_file_location("rsi_live_budget_ab", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


class LiveBudgetInvariantTests(unittest.TestCase):
    def test_predeclared_candidates_and_equal_order_budgets(self):
        self.assertEqual(live.BUDGET, 3)
        self.assertEqual([order for _, order, _ in live.ORDERS], [(0, 1), (1, 0)])
        for name, cohort in live.NEIGHBORHOODS.items():
            root = cohort["root"]
            step0 = cohort["c0-plus"][0] - root[0]
            step1 = cohort["c1-plus"][1] - root[1]
            with self.subTest(cohort=name):
                self.assertEqual(live.resolve_candidate(tuple(root), cohort), "root")
                for vector, expected in [
                    ((root[0] - step0, root[1]), "c0-minus"),
                    ((root[0] + step0, root[1]), "c0-plus"),
                    ((root[0], root[1] - step1), "c1-minus"),
                    ((root[0], root[1] + step1), "c1-plus"),
                ]:
                    self.assertEqual(live.resolve_candidate(vector, cohort), expected)
                self.assertEqual(len(cohort) - 1, 5)

    def test_unknown_nan_boolean_and_non_authored_cannot_trigger_browser(self):
        cohort = live.NEIGHBORHOODS["calibrated"]
        for values in ((1.2, 0.94), (), (0.9,), (0.9, 0.94, 1),
                       (math.nan, 0.94), (float("inf"), 0.94),
                       (True, 0.94), ("0.9", 0.94)):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    live.resolve_candidate(values, cohort)
        duplicated = {"root": [0, 0], "alias": [0, 0], "target": [1, 1]}
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            live.resolve_candidate((0, 0), duplicated)

    def world(self, base: Path, cohort_name: str = "calibrated"):
        cohort = live.NEIGHBORHOODS[cohort_name]
        variants = []
        for name in cohort:
            folder = base / name
            folder.mkdir(parents=True)
            spec = folder / "spec.json"
            model = folder / "model.ts"
            spec.write_text("spec for " + name, encoding="utf-8")
            model.write_text("model for " + name, encoding="utf-8")
            (folder / "browser.json").write_text(json.dumps({
                "ready": True, "coverage": 0.25, "errors": [],
                "webgl": "WebGL 2.0 (OpenGL ES)", "chromium": "fixture",
                "renderer": "WebKit",
            }), encoding="utf-8")
            variants.append({"name": name, "specSha256": live.sha256(spec),
                             "generatedTypeScriptSha256": live.sha256(model)})
        source = base / "target" / "render.png"
        source.write_bytes(b"independent target fixture")
        manifest = {
            "status": "prepared-not-rendered",
            "neighborhood": cohort_name,
            "parameters": cohort,
            "fixtureSha256": live.sha256(live.FIXTURE),
            "gitSha": "synthetic-hashed-run",
            "variants": variants,
        }
        result = {
            "status": "browser-render-and-native-divine-eye-measured",
            "neighborhood": cohort_name,
            "gitSha": "synthetic-hashed-run",
            "measuredFidelity": {"target": {"imageSha256": live.sha256(source)}},
        }
        (base / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (base / "results.json").write_text(json.dumps(result), encoding="utf-8")
        return manifest, result

    def test_frozen_world_and_reference_are_required(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.world(root)
            manifest, cohort, target = live.validated_world(root)
            self.assertEqual(manifest["neighborhood"], "calibrated")
            self.assertEqual(cohort["root"], [0.90, 0.94])
            self.assertTrue(target.is_file())
            target.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "stale or missing"):
                live.validated_world(root)

    def test_browser_receipt_and_spec_drift_fail_before_renders(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.world(root, "original")
            (root / "root" / "browser.json").write_text(
                json.dumps({"ready": "true", "errors": []}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unverified WebGL2"):
                live.validated_world(root)
            self.world_fix_browser(root)
            (root / "root" / "spec.json").write_text("changed spec", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "spec changed"):
                live.validated_world(root)

    @staticmethod
    def world_fix_browser(root: Path):
        (root / "root" / "browser.json").write_text(json.dumps({
            "ready": True, "coverage": 0.25, "errors": [],
            "webgl": "WebGL 2.0 (OpenGL ES)", "chromium": "fixture",
            "renderer": "WebKit",
        }), encoding="utf-8")

    def test_altered_cohort_and_candidate_order_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest, _ = self.world(root)
            manifest["variants"].reverse()
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "candidate list drifted"):
                live.validated_world(root)


if __name__ == "__main__":
    unittest.main()
