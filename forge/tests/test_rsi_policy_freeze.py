"""Synthetic controls for policy leakage, fallback and immutable holdout embargo.

These fixtures are not actual browser evidence and are never uploaded as
training data. The production freezer requires exactly 18 native receipts.
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
SPEC = importlib.util.spec_from_file_location("rsi_policy", EXP / "registered_policy.py")
assert SPEC and SPEC.loader
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)
import registered_multifamily as base  # noqa: E402

HASH = hashlib.sha256(b"synthetic-do-not-use-as-real-evidence").hexdigest()


def fake_report(world: dict, digest: str, *, prefer: int = 1) -> dict:
    scored = {}
    for name, vector in base.parameter_variants(world).items():
        score = .90 if name == "root" else .98 if name == f"c{prefer}-plus" else .90
        if name == "target":
            score = 1.0
        scored[name] = {
            "parameters": vector, "pngSha256": HASH, "specSha256": HASH,
            "fidelity": score, "silhouetteIoU": score,
            "approved": True, "hardGateFailures": [],
            "action": "continue", "verdict": "pass",
        }
    return {
        "status": "native-browser-measured",
        "worldId": world["id"], "family": world["family"], "split": world["split"],
        "sourceRegistrationSha256": digest,
        "sourceFixtureSha256": HASH, "referencePngSha256": HASH,
        "observed": scored,
        "trainingEligible": world["split"] == "train",
        "photographClaim": False, "learnedPolicyClaim": False,
    }


class PolicyFreezeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.train = self.root / "train"
        self.validation = self.root / "validation"
        self.train.mkdir()
        self.validation.mkdir()
        self.registry, self.digest = base.registration()

    def populate(self, *, train_prefer=1, validation_prefer=1):
        for world in self.registry["worlds"]:
            if world["split"] not in ("train", "validation"):
                continue
            root = self.train if world["split"] == "train" else self.validation
            file = root / world["id"] / "observations.json"
            file.parent.mkdir()
            file.write_text(json.dumps(fake_report(
                world, self.digest,
                prefer=train_prefer if world["split"] == "train" else validation_prefer,
            )), encoding="utf-8")

    def test_train_then_validation_freezes_without_holdout(self):
        self.populate()
        file = self.root / "frozen.json"
        lock = policy.freeze_policy(self.train, self.validation, file)
        self.assertEqual(lock["candidateOrder"], [1, 0])
        self.assertEqual(lock["coordinateOrder"], [1, 0])
        self.assertEqual(len(lock["trainingWorldIds"]), 12)
        self.assertEqual(len(lock["validationWorldIds"]), 6)
        self.assertTrue(lock["validationPassed"])
        self.assertFalse(lock["holdoutOpened"])
        self.assertEqual(lock["trainingOnlyPolicy"], True)
        self.assertEqual(lock["policyDigest"], hashlib.sha256(policy._canonical(
            {k: v for k, v in lock.items() if k != "policyDigest"}
        )).hexdigest())
        base.check_frozen_policy(file, self.digest)
        with self.assertRaises(FileExistsError):
            policy.freeze_policy(self.train, self.validation, file)

    def test_validation_veto_keeps_incumbent_without_relearning(self):
        self.populate(train_prefer=1, validation_prefer=0)
        lock = policy.freeze_policy(self.train, self.validation, self.root / "veto.json")
        self.assertEqual(lock["candidateOrder"], [1, 0])
        self.assertEqual(lock["coordinateOrder"], [0, 1])
        self.assertFalse(lock["validationPassed"])

    def test_missing_duplicate_or_leaked_split_cannot_freeze(self):
        self.populate()
        first = next(self.train.rglob("observations.json"))
        first.unlink()
        with self.assertRaisesRegex(ValueError, "need exactly"):
            policy.freeze_policy(self.train, self.validation, self.root / "nope.json")
        world = next(w for w in self.registry["worlds"] if w["split"] == "holdout")
        leaked = self.train / world["id"] / "observations.json"
        leaked.parent.mkdir()
        leaked.write_text(json.dumps(fake_report(world, self.digest)), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "non-allowed split"):
            policy.freeze_policy(self.train, self.validation, self.root / "nope.json")

    def test_bad_approval_or_modified_candidate_cannot_train(self):
        self.populate()
        file = next(self.train.rglob("observations.json"))
        report = json.loads(file.read_text(encoding="utf-8"))
        report["observed"]["c0-plus"].update(approved=True, verdict="low-confidence", action="probe")
        file.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "approval result misreported"):
            policy.freeze_policy(self.train, self.validation, self.root / "nope.json")
        report = json.loads(file.read_text(encoding="utf-8"))
        report["observed"]["c0-plus"].update(approved=False)
        report["observed"]["c0-plus"]["parameters"] = [123, 456]
        file.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "candidate geometry changed"):
            policy.freeze_policy(self.train, self.validation, self.root / "nope.json")

    def test_missing_native_decision_fields_cannot_claim_training_approval(self):
        # Core fitter has a legacy optional-action compatibility mode. The
        # preregistered study instead requires complete native-review receipts,
        # or an attacker could omit both fields to mark an unreviewed image clean.
        self.populate()
        path = next(self.train.rglob("observations.json"))
        original = path.read_text(encoding="utf-8")
        for field, replacement in (
            ("action", None), ("action", ""),
            ("verdict", None), ("verdict", ""),
        ):
            with self.subTest(field=field, replacement=replacement):
                report = json.loads(original)
                record = report["observed"]["c0-plus"]
                if replacement is None:
                    record.pop(field, None)
                else:
                    record[field] = replacement
                path.write_text(json.dumps(report), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "native review action and verdict"):
                    policy.freeze_policy(self.train, self.validation, self.root / "no-review.json")
                self.assertFalse((self.root / "no-review.json").exists())

    def test_unverified_validation_decisions_also_block_policy_freeze(self):
        self.populate()
        path = next(self.validation.rglob("observations.json"))
        report = json.loads(path.read_text(encoding="utf-8"))
        report["observed"]["root"].pop("verdict")
        path.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "native review action and verdict"):
            policy.freeze_policy(self.train, self.validation, self.root / "no-verdict.json")
        self.assertFalse((self.root / "no-verdict.json").exists())

    def test_probe_only_candidate_does_not_influence_learning(self):
        self.populate()
        records, _ = policy.collect(self.train, "train", self.registry, self.digest)
        for report in records.values():
            bad = report["observed"]["c1-plus"]
            bad.update(approved=False, action="probe", verdict="low-confidence",
                       silhouetteIoU=1.0, fidelity=0.99)
            # Training must not turn the tempting unapproved perfect IoU into a win.
            good = report["observed"]["c0-plus"]
            good.update(approved=True, action="continue", verdict="pass",
                        silhouetteIoU=0.96, fidelity=0.96)
        self.assertEqual(policy.train_priority(records), (0, 1))


if __name__ == "__main__":
    unittest.main()
