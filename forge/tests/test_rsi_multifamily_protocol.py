"""Regression gates for the 24-world, three-family source-generated RSI protocol."""
from __future__ import annotations

import importlib.util
from copy import deepcopy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / "experiments" / "dream_rsi_mesh_fidelity"
sys.path.insert(0, str(EXPERIMENT))
SPEC = importlib.util.spec_from_file_location("rsi_multifamily", EXPERIMENT / "registered_multifamily.py")
assert SPEC is not None and SPEC.loader is not None
rsi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rsi)


class RegisteredProtocolTest(unittest.TestCase):
    def test_exact_split_counts_and_nonoverlapping_ids(self) -> None:
        registry, digest = rsi.registration()
        self.assertEqual(len(digest), 64)
        self.assertEqual(len(registry["worlds"]), 24)
        self.assertEqual({family["id"] for family in registry["families"]}, set(rsi.FAMILIES))
        self.assertEqual({split: sum(w["split"] == split for w in registry["worlds"])
                          for split in rsi.REQUIRED_SPLITS}, rsi.REQUIRED_SPLITS)
        ids = [w["id"] for w in registry["worlds"]]
        self.assertEqual(len(set(ids)), 24)
        for family in rsi.FAMILIES:
            for split, expected in rsi.REQUIRED_PER_FAMILY.items():
                self.assertEqual(sum(w["family"] == family and w["split"] == split
                                     for w in registry["worlds"]), expected)

    def test_registered_source_is_hash_stable_and_duplicate_rejected(self) -> None:
        registry, original_digest = rsi.registration()
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "registration.json"
            file.write_text(json.dumps(registry) + "\n", encoding="utf-8")
            with patch.object(rsi, "REGISTRY", file):
                _, alternative_digest = rsi.registration()
                self.assertNotEqual(original_digest, alternative_digest)  # source bytes are committed
                modified = json.loads(file.read_text(encoding="utf-8"))
                modified["worlds"][1]["id"] = modified["worlds"][0]["id"]
                file.write_text(json.dumps(modified), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "duplicate"):
                    rsi.registration()

    def test_unknown_world_and_holdout_without_frozen_policy_fail_before_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "work"
            with self.assertRaisesRegex(ValueError, "unknown/ambiguous"):
                rsi.prepare_world(root, "made-up-id")
            self.assertFalse(root.exists())
            with self.assertRaisesRegex(ValueError, "holdout embargo"):
                rsi.prepare_world(root, "lathe-holdout-07")
            self.assertFalse(root.exists())

    def test_holdout_policy_cannot_use_validation_or_partial_training_data(self) -> None:
        registration, digest = rsi.registration()
        train_ids = [w["id"] for w in registration["worlds"] if w["split"] == "train"]
        validation_ids = [w["id"] for w in registration["worlds"] if w["split"] == "validation"]
        good = {
            "schema": "rsi-multifamily-policy-freeze-v1",
            "registrationSha256": digest,
            "coordinateOrder": [1, 0],
            "trainingWorldIds": train_ids,
            "validationWorldIds": validation_ids,
            "trainingReceiptSha256": {wid: "a" * 64 for wid in train_ids},
            "validationReceiptSha256": {wid: "b" * 64 for wid in validation_ids},
            "holdoutOpened": False, "holdoutObserved": False,
            "trainingOnlyPolicy": True, "photoFidelityClaim": False,
            "holdoutPerformanceClaim": False, "validationPassed": True,
        }

        def add_digest(record):
            record["policyDigest"] = hashlib.sha256(rsi._canonical({
                key: value for key, value in record.items() if key != "policyDigest"
            })).hexdigest()
            return record

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "frozen.json"
            path.write_text(json.dumps(add_digest(good)), encoding="utf-8")
            rsi.check_frozen_policy(path, digest)
            for mutate in (
                lambda d: d.update(coordinateOrder=[0, 0]),
                lambda d: d.update(trainingWorldIds=train_ids[:-1]),
                lambda d: d.update(trainingWorldIds=train_ids[:-1] + ["lathe-validation-05"]),
                lambda d: d.update(validationWorldIds=validation_ids[:-1]),
                lambda d: d.update(holdoutOpened=True),
                lambda d: d.update(holdoutObserved=True),
                lambda d: d.update(validationPassed=False),
                lambda d: d.update(registrationSha256="f" * 64),
            ):
                receipt = deepcopy(good)
                mutate(receipt)
                path.write_text(json.dumps(add_digest(receipt)), encoding="utf-8")
                with self.assertRaises(ValueError):
                    rsi.check_frozen_policy(path, digest)
            # Even a content edit with old valid metadata must fail the digest.
            receipt = deepcopy(good)
            receipt["candidateOrder"] = [0, 1]
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest"):
                rsi.check_frozen_policy(path, digest)

    def test_each_family_changes_real_generated_topology(self) -> None:
        # This calls the same native generator as the real Chromium job. A
        # default box fallback or malformed ObjectSculptSpec must fail here,
        # before any expensive browser setup.
        from forge.stage3_build.generate_threejs_factory import generate, filter_components_for_pass

        registry, _ = rsi.registration()
        fragment_by_family = {
            "assembled-box": "new THREE.BoxGeometry(",
            "lathe": "buildLatheGeometry(",
            "tapered-sweep": "buildTaperedSweepGeometry(",
        }
        for family, expression in fragment_by_family.items():
            world = next(w for w in registry["worlds"]
                         if w["family"] == family and w["split"] == "train")
            spec = rsi.spec_for_family(world, [1.0, 1.0])
            with self.subTest(family=family):
                self.assertEqual(spec["componentTree"][0]["primitive"],
                                 next(f["primitive"] for f in registry["families"] if f["id"] == family))
                in_blockout = filter_components_for_pass(
                    spec, spec["componentTree"], "blockout"
                )
                # V1's inherited macro lid dominated the visible profile.
                # Every v2 family must generate just its root silhouette.
                self.assertEqual([part["id"] for part in in_blockout], ["root"])
                generated = generate(spec, "blockout")
                self.assertIn(expression, generated)
                self.assertIn("import * as THREE from 'three'", generated)
                self.assertIn("createRsi", generated)
                self.assertEqual(spec["componentTree"][0]["transform"]["scale"], [1.0, 1.0, 1.0])

    def test_six_authored_candidates_are_distinct_and_within_safe_range(self) -> None:
        registry, _ = rsi.registration()
        for world in registry["worlds"]:
            vectors = rsi.parameter_variants(world)
            with self.subTest(world=world["id"]):
                self.assertEqual(tuple(vectors), rsi.VARIANT_ORDER)
                self.assertEqual(len({tuple(v) for v in vectors.values()}), 6)
                self.assertTrue(all(0.5 <= n <= 1.12 for v in vectors.values() for n in v))

    def test_score_refuses_unproduced_or_modified_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            with self.assertRaises((OSError, ValueError)):
                rsi.score_world(out)
            world, digest = rsi.registered_world("assembled-box-train-01")
            manifest = {
                "status": "prepared-not-rendered", "worldId": world["id"],
                "world": world, "registrationSha256": digest,
                "sourceFixtureSha256": rsi.sha256(rsi.SOURCE),
                "variants": [{"name": name} for name in rsi.VARIANT_ORDER],
            }
            (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises((OSError, ValueError)):
                rsi.score_world(out)  # no target PNG means no false positive

if __name__ == "__main__":
    unittest.main()
