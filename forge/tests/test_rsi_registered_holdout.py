"""Synthetic *only* controls for registered live holdout and summary integrity.

No fixtures here constitute real Chromium evidence, and no test writes to the
production experiment's browser artifact directory.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments" / "dream_rsi_mesh_fidelity"
sys.path.insert(0, str(EXP))
from registered_multifamily import FAMILIES, _canonical, registered_world, registration  # noqa: E402
from registered_holdout_ab import candidate_name, check_holdout  # noqa: E402
from aggregate_holdout import aggregate  # noqa: E402

HASH = hashlib.sha256(b"unit-test-only-no-real-evidence").hexdigest()


def synthetic_lock(digest: str, registry: dict) -> dict:
    train = sorted(w["id"] for w in registry["worlds"] if w["split"] == "train")
    validate = sorted(w["id"] for w in registry["worlds"] if w["split"] == "validation")
    lock = {
        "schema": "rsi-multifamily-policy-freeze-v1",
        "registrationSha256": digest, "coordinateOrder": [1, 0],
        "trainingWorldIds": train, "validationWorldIds": validate,
        "trainingReceiptSha256": {id: HASH for id in train},
        "validationReceiptSha256": {id: HASH for id in validate},
        "validationPassed": True, "holdoutOpened": False,
        "holdoutObserved": False, "trainingOnlyPolicy": True,
        "photoFidelityClaim": False, "holdoutPerformanceClaim": False,
    }
    lock["policyDigest"] = hashlib.sha256(_canonical(lock)).hexdigest()
    return lock


def captured(name: str, *, good: bool, order: int):
    if name == "root":
        value = 0.90
    elif name.endswith("minus"):
        value = 0.88
    else:
        value = 0.93 if order == 0 else 0.96
    return {
        "variant": name, "status": "captured",
        "pngSha256": HASH, "approved": good,
        "silhouetteIoU": value, "nativeFidelity": value,
        "hardGateFailures": [], "verdict": "pass", "action": "continue",
    }


def fake_live_holdout(world: dict, digest: str, policy_digest: str) -> dict:
    arms = {}
    for label, order in (("fixed", 0), ("frozen", 1)):
        names = ["root", f"c{order}-minus", f"c{order}-plus"]
        images = [captured(name, good=True, order=order) for name in names]
        arms[label] = {
            "coordinateOrder": [order, 1-order],
            "browserRendersInvoked": 3, "nativeEvaluatorCalls": 3,
            "bestApprovedSilhouetteIoU": max(x["silhouetteIoU"] for x in images),
            "hardGateFailureCount": 0,
            "evaluationsToTarget": 3 if order == 1 else None,
            "renders": images,
        }
    return {
        "schemaVersion": 1, "status": "completed",
        "sourceRegistrationSha256": digest, "frozenPolicyDigest": policy_digest,
        "worldId": world["id"], "family": world["family"], "split": world["split"],
        "referenceExcludedEqually": True, "preRenderedCandidateReuse": False,
        "freshBrowserRendersPerOrder": 3,
        "photographClaim": False, "physicalPrintClaim": False,
        "holdoutOrder": ["frozen", "fixed"] if world["profileId"] % 2 == 0 else ["fixed", "frozen"],
        "arms": arms,
    }


class HoldoutEvidenceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.registry, self.digest = registration()
        self.lock = synthetic_lock(self.digest, self.registry)
        self.policy_file = self.root / "frozen.json"
        self.policy_file.write_text(json.dumps(self.lock), encoding="utf-8")
        self.collect = self.root / "collection"
        self.collect.mkdir()

    def materialize(self):
        for world in self.registry["worlds"]:
            if world["split"] != "holdout":
                continue
            folder = self.collect / world["id"]
            folder.mkdir()
            (folder / "holdout-live-ab.json").write_text(
                json.dumps(fake_live_holdout(world, self.digest, self.lock["policyDigest"])),
                encoding="utf-8",
            )

    def test_unknown_candidate_does_not_trigger_arbitrary_browser(self):
        world, _ = registered_world("lathe-holdout-07")
        from registered_multifamily import parameter_variants
        authored = parameter_variants(world)
        self.assertEqual(candidate_name(tuple(world["initial"]), authored), "root")
        for invalid in ((3.0, .7), (.91,), (float("nan"), .9), (True, .9)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                candidate_name(invalid, authored)

    def test_missing_holdout_chrome_is_not_an_accepted_result(self):
        with self.assertRaises((OSError, ValueError)):
            check_holdout(self.root / "absent", self.policy_file)

    def test_all_six_mock_receipts_are_required_before_summary(self):
        self.materialize()
        reports = list(self.collect.rglob("holdout-live-ab.json"))
        self.assertEqual(len(reports), 6)
        destination = self.root / "summary.json"
        measured = aggregate(self.collect, self.policy_file, destination)
        self.assertTrue(measured["holdoutGateSatisfied"])  # synthetic scenario only
        self.assertEqual(measured["worldCount"], 6)
        self.assertAlmostEqual(measured["medianIoUDelta"], 0.03)
        self.assertEqual(measured["frozenPolicyDigest"], self.lock["policyDigest"])
        self.assertTrue(destination.exists())
        with self.assertRaises(FileExistsError):
            aggregate(self.collect, self.policy_file, destination)

    def test_missing_world_or_forged_policy_digest_refused(self):
        self.materialize()
        source = next(self.collect.rglob("holdout-live-ab.json"))
        source.unlink()
        with self.assertRaisesRegex(ValueError, "six distinct"):
            aggregate(self.collect, self.policy_file, self.root / "summary.json")
        self.materialize_missing(source)
        x = json.loads(source.read_text(encoding="utf-8"))
        x["frozenPolicyDigest"] = "0" * 64
        source.write_text(json.dumps(x), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "different frozen policy"):
            aggregate(self.collect, self.policy_file, self.root / "summary.json")

    def materialize_missing(self, file: Path):
        world, _ = registered_world(file.parent.name)
        file.write_text(json.dumps(fake_live_holdout(
            world, self.digest, self.lock["policyDigest"],
        )), encoding="utf-8")

    def test_fake_perfect_score_without_approved_browser_signal_is_refused(self):
        self.materialize()
        source = next(self.collect.rglob("holdout-live-ab.json"))
        data = json.loads(source.read_text(encoding="utf-8"))
        data["arms"]["fixed"]["bestApprovedSilhouetteIoU"] = 1.0
        source.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            aggregate(self.collect, self.policy_file, self.root / "summary.json")


if __name__ == "__main__":
    unittest.main()
