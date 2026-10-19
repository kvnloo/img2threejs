#!/usr/bin/env python3
"""Pre-registered multi-family ObjectSculptSpec -> Three.js -> Divine Eye trial.

The committed registry fixes three genuinely different procedural primitive
families and 12/6/6 train/validation/holdout worlds before their browser run.
This file is an experiment harness, not a photorealistic or blinded benchmark.
Never score a holdout before the training policy is frozen and checked.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "forge/tests/fixtures/reference_target_conformance_spec.json"
GENERATOR = ROOT / "forge/stage3_build/generate_threejs_factory.py"
REGISTRY = Path(__file__).with_name("MULTIFAMILY_V1_REGISTERED.json")
sys.path.insert(0, str(ROOT))
from forge.stage4_review.fit_params import FitInputError  # noqa: E402
from forge.stage4_review._fit_divine_eye import is_approved_divine_eye_result  # noqa: E402
from forge.stage4_review.divine_eye import evaluate  # noqa: E402
from real_render_smoke import IMAGE_SIZE, VIEWER, HTML, sha256, verify_browser_receipt  # noqa: E402

FAMILIES = ("assembled-box", "lathe", "tapered-sweep")
REQUIRED_SPLITS = {"train": 12, "validation": 6, "holdout": 6}
REQUIRED_PER_FAMILY = {"train": 4, "validation": 2, "holdout": 2}
VARIANT_ORDER = ("target", "root", "c0-minus", "c0-plus", "c1-minus", "c1-plus")
VEC_KEYS = ("initial", "target", "coordinateStep")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def registration() -> tuple[dict[str, Any], str]:
    raw = REGISTRY.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("schema") != "img2threejs-multifamily-v1":
        raise ValueError("unknown multifamily protocol schema")
    worlds = payload.get("worlds")
    if not isinstance(worlds, list) or len(worlds) != 24:
        raise ValueError("registered world count must be exactly 24")
    if tuple(row.get("id") for row in payload["families"]) != FAMILIES:
        raise ValueError("registered primitive families were changed")
    ids: set[str] = set()
    grouped: dict[str, dict[str, int]] = {family: {s: 0 for s in REQUIRED_SPLITS} for family in FAMILIES}
    for row in worlds:
        if not isinstance(row, dict):
            raise ValueError("registered world is not an object")
        wid, family, split = row.get("id"), row.get("family"), row.get("split")
        if (
            not isinstance(wid, str) or wid in ids or family not in FAMILIES
            or split not in REQUIRED_SPLITS or not wid.startswith(f"{family}-{split}-")
        ):
            raise ValueError("duplicate, unexpected or mislabeled registered world")
        ids.add(wid)
        if not isinstance(row.get("profileId"), int) or isinstance(row["profileId"], bool) or not 1 <= row["profileId"] <= 8:
            raise ValueError("registered profile ID out of range")
        grouped[family][split] += 1
        for key in VEC_KEYS:
            vector = row.get(key)
            if not isinstance(vector, list) or len(vector) != 2 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in vector
            ):
                raise ValueError(f"invalid registered {wid}.{key}")
        if row["target"] != [1, 1] or row["coordinateStep"] != [0.08, 0.08]:
            raise ValueError("target vector or step differs from locked protocol")
        if not all(0.5 <= x <= 1.12 for x in row["initial"]):
            raise ValueError("root outside predeclared safe fitting envelope")
    if any(counts != REQUIRED_PER_FAMILY for counts in grouped.values()):
        raise ValueError("family split quotas or world membership changed")
    if {split: sum(by[split] for by in grouped.values()) for split in REQUIRED_SPLITS} != REQUIRED_SPLITS:
        raise ValueError("global split quotas changed")
    if payload.get("splitSizes") != REQUIRED_SPLITS or payload.get("budgets") != [3, 5]:
        raise ValueError("locked protocol split or budget changed")
    return payload, hashlib.sha256(raw).hexdigest()


def registered_world(world_id: str) -> tuple[dict[str, Any], str]:
    payload, digest = registration()
    matched = [world for world in payload["worlds"] if world["id"] == world_id]
    if len(matched) != 1:
        raise ValueError("unknown/ambiguous preregistered world ID")
    return matched[0], digest


def spec_for_family(world: dict[str, Any], vector: list[float]) -> dict[str, Any]:
    """Change geometry topology, not merely the name or a global scale."""
    if not all(isinstance(v, (int, float)) and 0.5 <= v <= 1.12 for v in vector):
        raise ValueError("parameter vector outside preregistered range")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    item = source["componentTree"][0]
    if item.get("id") != "root" or item.get("level") != "macro":
        raise ValueError("canonical source fixture root was replaced")
    family, profile = world["family"], world["profileId"]
    source["targetName"] = f"Rsi {family.replace('-', ' ')} V1"
    source["targetId"] = f"rsi-{family}-v1"
    item["name"] = f"{family} root body"
    item["topologyRationale"] = "Controlled procedural profile generated from an immutable public reference template."
    if family == "assembled-box":
        # Rounded, tapered hard-surface block from the original project fixture.
        item["primitive"] = "box"
        descriptor = item["geometryDescriptor"]
        descriptor["edgeTreatment"]["bevelRadius"] = round(0.030 + 0.003 * profile, 4)
        descriptor["deformationStack"][0]["factor"] = round(0.79 + 0.015 * profile, 4)
        item["dimensions"].update(width=1.0, height=0.62, depth=0.78)
    elif family == "lathe":
        # A rotational multi-station outline (not a box made taller).
        radius_variation = 0.015 * profile
        item["primitive"] = "lathe"
        item["geometryDescriptor"] = {
            "topologyIntent": "rotational vessel with unequal shoulder and waist sections",
            "latheProfile": {
                "points": [
                    [round(0.26 + radius_variation, 4), -0.5],
                    [round(0.42 + radius_variation, 4), -0.33],
                    [round(0.28 + radius_variation / 2, 4), -0.06],
                    [round(0.38 - radius_variation / 3, 4), 0.27],
                    [round(0.20 + radius_variation / 3, 4), 0.5],
                ], "segments": 32,
            },
            "uvStrategy": "generated procedural coordinates",
            "normalStrategy": "vertex normals from generated geometry",
        }
        item["dimensions"].update(width=1.25, height=1.20, depth=1.20)
    elif family == "tapered-sweep":
        # A changing elliptical cross-section along a bent 3D centerline.
        bend = 0.012 * profile
        item["primitive"] = "tapered-sweep"
        item["geometryDescriptor"] = {
            "topologyIntent": "bent asymmetric narrowing solid, four measured elliptical stations",
            "taperedSweep": {
                "stations": [
                    {"position": [-0.12, -0.5, 0.0], "rx": 0.40, "rz": 0.33, "twist": 0.0},
                    {"position": [round(-0.06 + bend, 4), -0.12, 0.02],
                     "rx": 0.35, "rz": 0.30, "twist": 0.04},
                    {"position": [round(0.07 + bend, 4), 0.23, -0.02],
                     "rx": 0.23, "rz": 0.20, "twist": 0.08},
                    {"position": [round(0.15 + bend, 4), 0.5, 0.0],
                     "rx": 0.08, "rz": 0.07, "twist": 0.1},
                ],
                "radialSegments": 16, "capEnds": True,
            },
            "uvStrategy": "generated procedural coordinates",
            "normalStrategy": "vertex normals from generated geometry",
        }
        item["dimensions"].update(width=1.45, height=1.22, depth=1.45)
    else:
        raise ValueError("unknown registered shape family")
    item["transform"]["scale"] = [float(vector[0]), 1.0, float(vector[1])]
    return source


def parameter_variants(world: dict[str, Any]) -> dict[str, list[float]]:
    root = world["initial"]
    dx, dz = world["coordinateStep"]
    return {
        "target": world["target"],
        "root": root,
        "c0-minus": [round(root[0] - dx, 8), root[1]],
        "c0-plus": [round(root[0] + dx, 8), root[1]],
        "c1-minus": [root[0], round(root[1] - dz, 8)],
        "c1-plus": [root[0], round(root[1] + dz, 8)],
    }


def check_frozen_policy(path: Path | None, registration_sha: str) -> None:
    if path is None:
        raise ValueError("registered holdout embargo: freeze a training-only policy first")
    lock = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(lock, dict) or lock.get("schema") != "rsi-multifamily-policy-freeze-v1":
        raise ValueError("unknown holdout policy freeze schema")
    if lock.get("registrationSha256") != registration_sha:
        raise ValueError("frozen policy references another registration")
    if lock.get("coordinateOrder") not in ([0, 1], [1, 0]):
        raise ValueError("frozen policy coordinate order invalid")
    registered = registration()[0]["worlds"]
    training_ids = {w["id"] for w in registered if w["split"] == "train"}
    validation_ids = {w["id"] for w in registered if w["split"] == "validation"}
    for field, expected in (
        ("trainingWorldIds", training_ids),
        ("validationWorldIds", validation_ids),
    ):
        actual = lock.get(field)
        if not isinstance(actual, list) or len(actual) != len(expected) or set(actual) != expected:
            raise ValueError(f"policy freeze lacks complete, split-isolated {field}")
    for field, expected in (
        ("trainingReceiptSha256", training_ids),
        ("validationReceiptSha256", validation_ids),
    ):
        receipts = lock.get(field)
        if (
            not isinstance(receipts, dict) or set(receipts) != expected
            or any(not isinstance(v, str) or len(v) != 64
                   or any(c not in "0123456789abcdef" for c in v)
                   for v in receipts.values())
        ):
            raise ValueError(f"policy freeze lacks hashed native evidence in {field}")
    if (
        lock.get("holdoutOpened") is not False
        or lock.get("holdoutObserved") is not False
        or lock.get("trainingOnlyPolicy") is not True
        or lock.get("photoFidelityClaim") is not False
        or lock.get("holdoutPerformanceClaim") is not False
    ):
        raise ValueError("holdout results leaked or false policy provenance claimed")
    if lock.get("validationPassed") is not True:
        raise ValueError("validation vetoed policy; cannot run learned-order holdout")
    digest_value = lock.get("policyDigest")
    canonical_lock = {k: v for k, v in lock.items() if k != "policyDigest"}
    if digest_value != hashlib.sha256(_canonical(canonical_lock)).hexdigest():
        raise ValueError("frozen policy digest mismatch or tampering detected")


def prepare_world(out: Path, world_id: str, *, policy: Path | None = None) -> None:
    world, registration_sha = registered_world(world_id)
    if world["split"] == "holdout":
        check_frozen_policy(policy, registration_sha)
    if out.exists() and any(out.iterdir()):
        raise ValueError("output directory already contains files; never reuse prior candidate evidence")
    out.mkdir(parents=True, exist_ok=True)
    parameters = parameter_variants(world)
    source_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=15,
    ).strip()
    expected_head = os.environ.get("SOURCE_HEAD_SHA")
    if expected_head and source_head != expected_head:
        raise ValueError("checkout differs from expected source commit")
    manifest: dict[str, Any] = {
        "schemaVersion": 1, "status": "prepared-not-rendered",
        "sourceGitSha": source_head,
        "generatorSha256": sha256(GENERATOR),
        "browserRunnerSha256": sha256(Path(__file__).with_name("real_browser_capture.mjs")),
        "worldId": world_id, "family": world["family"], "split": world["split"],
        "world": deepcopy(world), "registrationSha256": registration_sha,
        "sourceFixtureSha256": sha256(SOURCE),
        "generatedFrom": "native ObjectSculptSpec -> generate_threejs_factory.py --pass-id blockout",
        "size": IMAGE_SIZE, "variants": [],
        "measuredFidelity": None,
    }
    for name, vector in parameters.items():
        spec = spec_for_family(world, vector)
        folder = out / name
        folder.mkdir()
        spec_path, model_path = folder / "spec.json", folder / "model.ts"
        spec_path.write_text(json.dumps(spec, sort_keys=True) + "\n", encoding="utf-8")
        generated = subprocess.run(
            [sys.executable, str(GENERATOR), str(spec_path),
             "--out", str(model_path), "--pass-id", "blockout", "--force"],
            cwd=ROOT, capture_output=True, text=True, check=False, timeout=90,
        )
        if generated.returncode:
            raise RuntimeError(f"native generator refused {world_id}/{name}: {generated.stderr[-1700:]}")
        function_name = "createRsi" + "".join(
            token[:1].upper() + token[1:]
            for token in world["family"].split("-")
        ) + "V1Model"
        viewer = VIEWER.replace("createTradeItHardCaseModel", function_name)
        (folder / "viewer.ts").write_text(viewer, encoding="utf-8")
        (folder / "index.html").write_text(HTML, encoding="utf-8")
        manifest["variants"].append({
            "name": name, "parameters": vector,
            "specSha256": sha256(spec_path),
            "generatedTypeScriptSha256": sha256(model_path),
        })
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def score_world(out: Path, *, policy: Path | None = None) -> dict[str, Any]:
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("status") != "prepared-not-rendered":
        raise ValueError("scoring needs a prepared-only world manifest")
    world, digest = registered_world(manifest.get("worldId"))
    if manifest.get("world") != world or manifest.get("registrationSha256") != digest:
        raise ValueError("world/registration hash or content changed after preregistration")
    if sha256(SOURCE) != manifest.get("sourceFixtureSha256"):
        raise ValueError("source spec fixture changed after preparation")
    if (
        manifest.get("generatorSha256") != sha256(GENERATOR)
        or manifest.get("browserRunnerSha256") != sha256(Path(__file__).with_name("real_browser_capture.mjs"))
    ):
        raise ValueError("generator or browser runner changed since preparation")
    recorded_head = manifest.get("sourceGitSha")
    if not isinstance(recorded_head, str) or len(recorded_head) != 40:
        raise ValueError("missing immutable source Git SHA")
    if world["split"] == "holdout":
        check_frozen_policy(policy, digest)
    parameters = parameter_variants(world)
    if [v.get("name") for v in manifest.get("variants", [])] != list(parameters):
        raise ValueError("candidate set changed after preparation")
    reference = out / "target" / "render.png"
    if not reference.is_file():
        raise ValueError("native Chromium target screenshot missing")
    scored: dict[str, Any] = {}
    for variant in manifest["variants"]:
        name = variant["name"]
        if variant.get("parameters") != parameters[name]:
            raise ValueError("candidate parameter vector drifted from preregistered root")
        folder = out / name
        spec = folder / "spec.json"
        generated = folder / "model.ts"
        if sha256(spec) != variant.get("specSha256") or sha256(generated) != variant.get("generatedTypeScriptSha256"):
            raise ValueError("source model/spec hash drift")
        parsed = json.loads(spec.read_text(encoding="utf-8"))
        if parsed != spec_for_family(world, variant["parameters"]):
            raise ValueError("candidate source geometry modified after registration")
        verify_browser_receipt(folder, name)
        png = folder / "render.png"
        raw = png.read_bytes()
        if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 24:
            raise ValueError("capture did not contain a genuine PNG header")
        if struct.unpack(">II", raw[16:24]) != (IMAGE_SIZE, IMAGE_SIZE):
            raise ValueError("PNG dimensions do not match frozen renderer")
        verdict = evaluate(reference, png)
        if not isinstance(verdict, dict):
            raise ValueError("native evaluator did not return a verdict")
        signal = verdict.get("signals", {}).get("silhouetteIoU")
        if isinstance(signal, bool) or not isinstance(signal, (int, float)) or not math.isfinite(signal) or not 0 <= signal <= 1:
            raise ValueError("native silhouette IoU unavailable")
        approved = is_approved_divine_eye_result(verdict, FitInputError, "Divine Eye result")
        scored[name] = {
            "parameters": variant["parameters"],
            "pngSha256": sha256(png),
            "specSha256": variant["specSha256"],
            "silhouetteIoU": signal,
            "fidelity": verdict["fidelity"],
            "hardGateFailures": verdict["hardGateFailures"],
            "verdict": verdict["verdict"], "action": verdict["action"],
            "approved": approved,
        }
        (folder / "divine-eye.json").write_text(json.dumps(verdict, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if scored["target"]["silhouetteIoU"] < 0.999:
        raise ValueError("native evaluator target self-match is not IoU 1")
    report = {
        "schemaVersion": 1, "status": "native-browser-measured",
        "worldId": world["id"], "family": world["family"], "split": world["split"],
        "sourceRegistrationSha256": digest,
        "sourceFixtureSha256": manifest["sourceFixtureSha256"],
        "referencePngSha256": sha256(reference),
        "observed": scored,
        "trainingEligible": world["split"] == "train",
        "photographClaim": False, "learnedPolicyClaim": False,
        "holdoutClaim": False, "renderBudgetClaim": False,
        "limitation": "full root-neighborhood capture; not yet the equal-budget live-fitter ABAB study",
    }
    target = out / "observations.json"
    if target.exists():
        raise ValueError("world observations already published; refuse overwrite")
    target.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase", choices=("register", "prepare", "score"))
    ap.add_argument("--out", type=Path)
    ap.add_argument("--world-id", default="")
    ap.add_argument("--policy", type=Path, help="required prior frozen training-only policy for holdout access")
    args = ap.parse_args(argv)
    try:
        if args.phase == "register":
            protocol, digest = registration()
            result = {"registrationSha256": digest, "familyCount": len(FAMILIES),
                      "worldCount": len(protocol["worlds"]),
                      "splitSizes": REQUIRED_SPLITS, "holdoutEmbargo": True}
        else:
            if args.out is None:
                raise ValueError("prepare/score requires --out")
            path = args.out.expanduser().resolve()
            if args.phase == "prepare":
                prepare_world(path, args.world_id, policy=args.policy)
                result = {"status": "prepared", "worldId": args.world_id}
            else:
                report = score_world(path, policy=args.policy)
                result = {
                    "status": report["status"], "worldId": report["worldId"],
                    "approvedCandidateCount": sum(x["approved"] for x in report["observed"].values()),
                    "observedReferenceMatch": report["observed"]["target"]["silhouetteIoU"],
                    "trainingEligible": report["trainingEligible"],
                }
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, KeyError, TypeError) as error:
        # No raw spec/image/browser JSON forwarded into CLI logs.
        print(f"multifamily research input/experiment failure: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
