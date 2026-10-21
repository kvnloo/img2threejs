#!/usr/bin/env python3
"""Locked-policy holdout: fresh Chromium candidate renders at equal budgets.

The policy must be frozen using *all* 12 training + 6 validation browser
receipts before this script can see any of the six reserved holdout worlds.
Only known, source-hashed candidate specs may be rendered. Existing PNGs from
the world neighborhood are never returned to the objective callback.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BROWSER = Path(__file__).with_name("real_browser_capture.mjs")
sys.path.insert(0, str(ROOT))
from forge.stage4_review.fit_params import FitConfig, FitInputError, fit_against_divine_eye  # noqa: E402
from forge.stage4_review._fit_divine_eye import is_approved_divine_eye_result  # noqa: E402
from forge.stage4_review.divine_eye import evaluate  # noqa: E402
from registered_multifamily import (  # noqa: E402
    IMAGE_SIZE, check_frozen_policy, parameter_variants, registered_world,
    sha256, verify_browser_receipt,
)

BUDGET = 3
BASELINE = (0, 1)


def candidate_name(parameters: tuple[float, ...], variants: dict[str, list[float]]) -> str:
    if len(parameters) != 2 or any(
        isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n)
        for n in parameters
    ):
        raise ValueError("holdout requested invalid numeric coordinates")
    names = [
        name for name, authored in variants.items()
        if name != "target" and len(authored) == 2
        and all(abs(float(a) - float(b)) < 1e-9 for a, b in zip(parameters, authored))
    ]
    if len(names) != 1:
        raise ValueError("holdout requested non-preregistered or ambiguous geometry")
    return names[0]


def check_holdout(out: Path, frozen_policy: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("status") != "prepared-not-rendered":
        raise ValueError("holdout requires a prepared, uncompromised world")
    world, digest = registered_world(manifest.get("worldId"))
    if world["split"] != "holdout" or world != manifest.get("world"):
        raise ValueError("attempted holdout evaluation of an unregistered/non-holdout world")
    if manifest.get("registrationSha256") != digest:
        raise ValueError("holdout registration hash mismatch")
    check_frozen_policy(frozen_policy, digest)
    registered = parameter_variants(world)
    if [v.get("name") for v in manifest.get("variants", [])] != list(registered):
        raise ValueError("altered or incomplete holdout candidate set")
    for record in manifest["variants"]:
        name = record["name"]
        if record.get("parameters") != registered[name]:
            raise ValueError("registered holdout parameters were replaced")
        folder = out / name
        if sha256(folder / "spec.json") != record.get("specSha256"):
            raise ValueError("holdout spec hash changed after policy freeze")
        if sha256(folder / "model.ts") != record.get("generatedTypeScriptSha256"):
            raise ValueError("holdout generated model changed after policy freeze")
        verify_browser_receipt(folder, name)
    target = out / "target" / "render.png"
    if not target.is_file() or target.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("holdout target lacks Chromium PNG evidence")
    return manifest, world, target


def execute(out: Path, policy_file: Path) -> dict[str, Any]:
    manifest, world, reference = check_holdout(out, policy_file)
    policy = json.loads(policy_file.read_text(encoding="utf-8"))
    learned = tuple(policy["coordinateOrder"])
    if learned not in ((0, 1), (1, 0)):
        raise ValueError("frozen coordinate order invalid")
    vectors = parameter_variants(world)
    step = world["coordinateStep"]
    root = world["initial"]
    bounds = tuple((value - 2 * delta, value + 2 * delta)
                   for value, delta in zip(root, step))
    policies = (("fixed", BASELINE), ("frozen", learned))
    # Counterbalance fixed/frozen first across the two holdout variants.
    if world["profileId"] % 2 == 0:
        policies = tuple(reversed(policies))
    report_file = out / "holdout-live-ab.json"
    if report_file.exists():
        raise ValueError("holdout verdict already exists: refuse repetition/peek")
    report: dict[str, Any] = {
        "schemaVersion": 1, "status": "in-progress",
        "kind": "preregistered-frozen-policy-on-demand-chromium-ab",
        "sourceRegistrationSha256": manifest["registrationSha256"],
        "sourceGitSha": manifest.get("sourceGitSha"),
        "worldId": world["id"], "family": world["family"], "split": world["split"],
        "frozenPolicyDigest": policy["policyDigest"],
        "referencePngSha256": sha256(reference),
        "referenceExcludedEqually": True, "preRenderedCandidateReuse": False,
        "freshBrowserRendersPerOrder": BUDGET,
        "trainingResultReused": False,
        "holdoutOrder": [name for name, _ in policies],
        "photographClaim": False, "physicalPrintClaim": False,
        "arms": {},
    }
    report_file.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    for label, coordinate_order in policies:
        calls: list[dict[str, Any]] = []
        started = time.perf_counter()

        def render_live(parameters: tuple[float, ...]) -> Path:
            name = candidate_name(parameters, vectors)
            if len(calls) >= BUDGET:
                raise RuntimeError("browser render budget exceeded before invoking Chromium")
            tag = f"holdout-{label}-{len(calls) + 1}"
            folder = out / name
            png, receipt = folder / f"{tag}.png", folder / f"{tag}.json"
            if png.exists() or receipt.exists():
                raise ValueError("existing candidate PNG cannot be reused or overwritten")
            entry: dict[str, Any] = {"variant": name, "tag": tag, "status": "launched"}
            calls.append(entry)
            invoked = time.perf_counter()
            proc = subprocess.run(
                ["node", str(BROWSER), str(out), "--variant", name, "--tag", tag],
                cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
                env=os.environ.copy(),
            )
            entry["wallSeconds"] = round(time.perf_counter() - invoked, 3)
            if proc.returncode:
                entry["status"] = "failed"
                raise RuntimeError(f"real Chromium render did not complete for {tag}")
            events = [json.loads(line) for line in proc.stdout.splitlines()
                      if line.lstrip().startswith("{")]
            if (
                len(events) != 1
                or events[0].get("variant") != name
                or events[0].get("captureTag") != tag
                or events[0].get("liveCapture") is not True
            ):
                raise RuntimeError("fresh browser capture did not match requested candidate")
            if not png.is_file() or png.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                raise RuntimeError("fresh Chromium PNG missing")
            if struct.unpack(">II", png.read_bytes()[16:24]) != (IMAGE_SIZE, IMAGE_SIZE):
                raise RuntimeError("holdout screenshot dimensions changed")
            verify_browser_receipt(folder, name, receipt_name=receipt.name)
            browser = json.loads(receipt.read_text(encoding="utf-8"))
            if browser.get("variant") != name or browser.get("captureTag") != tag:
                raise RuntimeError("holdout browser receipt attributed to wrong model")
            entry["pngSha256"] = sha256(png)
            entry["status"] = "captured"
            return png

        fitted = fit_against_divine_eye(
            root, bounds, render_live, reference, evaluate,
            FitConfig(max_evaluations=BUDGET, coordinate_order=coordinate_order),
        )
        visited = [entry["variant"] for entry in calls]
        expected = ["root", f"c{coordinate_order[0]}-minus", f"c{coordinate_order[0]}-plus"]
        if visited != expected or fitted.fit_result.evaluations != BUDGET or len(calls) != BUDGET:
            raise RuntimeError(f"holdout candidate order/evaluation budget drift in {label}")
        if any(entry["status"] != "captured" for entry in calls):
            raise RuntimeError("failed browser render counted as observed")
        if fitted.fit_result.best_score != fitted.fit_result.history[-1].best_score:
            raise RuntimeError("selected result is inconsistent with correction history")
        approved = []
        evaluations_to_target = None
        for step_number, (row, native) in enumerate(zip(calls, fitted.divine_eye_results), 1):
            ok = is_approved_divine_eye_result(native, FitInputError, "Divine Eye result")
            value = native["signals"]["silhouetteIoU"]
            row.update({
                "nativeFidelity": native["fidelity"], "silhouetteIoU": value,
                "hardGateFailures": native["hardGateFailures"],
                "verdict": native["verdict"], "action": native["action"], "approved": ok,
            })
            if ok:
                approved.append(value)
                if evaluations_to_target is None and value >= 0.96:
                    evaluations_to_target = step_number
        report["arms"][label] = {
            "coordinateOrder": list(coordinate_order),
            "browserRendersInvoked": len(calls),
            "nativeEvaluatorCalls": fitted.fit_result.evaluations,
            "wallSeconds": round(time.perf_counter() - started, 3),
            "bestApprovedSilhouetteIoU": max(approved, default=None),
            "bestAcceptedFidelity": fitted.best_raw_fidelity,
            "evaluationsToTarget": evaluations_to_target,
            "hardGateFailureCount": sum(bool(x["hardGateFailures"]) for x in calls),
            "renders": calls,
            "fitResult": fitted.fit_result.to_json(),
        }
        report_file.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    report["status"] = "completed"
    report["limitation"] = (
        "predeclared public procedural target, split-isolated training/validation and locked policy; "
        "not an independent human-blind experiment or photo reconstruction"
    )
    report_file.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--policy", type=Path, required=True)
    args = p.parse_args()
    try:
        report = execute(args.out.expanduser().resolve(), args.policy.expanduser().resolve())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, KeyError, TypeError) as error:
        print(f"registered holdout refused: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": report["status"], "worldId": report["worldId"],
        "policyDigest": report["frozenPolicyDigest"],
        "arms": {k: {
            "bestApprovedSilhouetteIoU": v["bestApprovedSilhouetteIoU"],
            "evaluationsToTarget": v["evaluationsToTarget"],
            "browserRendersInvoked": v["browserRendersInvoked"],
            "nativeEvaluatorCalls": v["nativeEvaluatorCalls"],
            "wallSeconds": v["wallSeconds"],
        } for k, v in report["arms"].items()},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
