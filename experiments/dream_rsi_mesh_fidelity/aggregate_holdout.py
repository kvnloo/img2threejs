#!/usr/bin/env python3
"""Preregistered six-world holdout verdict, with no policy tuning permitted.

A passing GitHub Actions workflow only means the measurement process ran.
The conclusion may be NO ADVANTAGE. No real-photo or human-blind claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median, mean
import sys
from typing import Any

from registered_multifamily import (
    FAMILIES, _canonical, check_frozen_policy, registered_world, registration,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_evidence(folder: Path, frozen: dict[str, Any], expected_digest: str) -> tuple[dict[str, Any], str]:
    file = folder / "holdout-live-ab.json"
    data = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("status") != "completed":
        raise ValueError("holdout measurement is missing or incomplete")
    world, digest = registered_world(data.get("worldId"))
    if (
        digest != expected_digest or data.get("sourceRegistrationSha256") != digest
        or data.get("split") != "holdout" or world["split"] != "holdout"
        or data.get("family") != world["family"]
    ):
        raise ValueError("holdout evidence belongs to a different split/registration")
    if data.get("frozenPolicyDigest") != frozen["policyDigest"]:
        raise ValueError("holdout was run under a different frozen policy")
    if data.get("referenceExcludedEqually") is not True or data.get("preRenderedCandidateReuse") is not False:
        raise ValueError("holdout was not a fresh, identically budgeted Chromium experiment")
    if data.get("freshBrowserRendersPerOrder") != 3:
        raise ValueError("holdout render budget changed")
    if data.get("photographClaim") is not False or data.get("physicalPrintClaim") is not False:
        raise ValueError("holdout artifact asserts unsupported real-world acceptance")
    arms = data.get("arms")
    if not isinstance(arms, dict) or set(arms) != {"fixed", "frozen"}:
        raise ValueError("holdout must contain both original and frozen arms")
    for name, order in (("fixed", [0, 1]), ("frozen", frozen["coordinateOrder"])):
        arm = arms[name]
        if arm.get("coordinateOrder") != order or arm.get("browserRendersInvoked") != 3 or arm.get("nativeEvaluatorCalls") != 3:
            raise ValueError("policy execution order or equal budget was not respected")
        value = arm.get("bestApprovedSilhouetteIoU")
        if value is not None and (not _is_numeric(value) or not 0 <= value <= 1):
            raise ValueError("invalid best approved native silhouette metric")
        visits = arm.get("renders")
        if not isinstance(visits, list) or len(visits) != 3 or any(
            x.get("status") != "captured" or not isinstance(x.get("pngSha256"), str)
            or len(x["pngSha256"]) != 64
            for x in visits if isinstance(x, dict)
        ):
            raise ValueError("browser capture count/sha receipt is incomplete")
        if any(not isinstance(x, dict) for x in visits):
            raise ValueError("invalid browser capture receipt")
        expected = ["root", f"c{order[0]}-minus", f"c{order[0]}-plus"]
        if [x.get("variant") for x in visits] != expected:
            raise ValueError("holdout fitter rendered different than frozen policy")
        approved = [
            float(x["silhouetteIoU"]) for x in visits
            if x.get("approved") is True
        ]
        if value != (max(approved) if approved else None):
            raise ValueError("selected silhouette result inconsistent with native browser receipts")
        failures = sum(bool(x.get("hardGateFailures")) for x in visits)
        if arm.get("hardGateFailureCount") != failures:
            raise ValueError("hard gate failure accounting mismatch")
        target_time = arm.get("evaluationsToTarget")
        correct_time = next((idx for idx, x in enumerate(visits, start=1)
                             if x.get("approved") is True and x.get("silhouetteIoU", -1) >= 0.96), None)
        if target_time != correct_time:
            raise ValueError("evaluations-to-target claim contradicted by recorded native evaluations")
    return data, _sha256(file)


def aggregate(root: Path, policy_file: Path, report_file: Path) -> dict[str, Any]:
    frozen = json.loads(policy_file.read_text(encoding="utf-8"))
    _, digest = registration()
    check_frozen_policy(policy_file, digest)
    ids = {w["id"] for w in registration()[0]["worlds"] if w["split"] == "holdout"}
    records: dict[str, dict[str, Any]] = {}
    receipt_hashes: dict[str, str] = {}
    for file in sorted(root.rglob("holdout-live-ab.json")):
        record, sha = read_evidence(file.parent, frozen, digest)
        name = record["worldId"]
        if name in records:
            raise ValueError("duplicate holdout world in evidence bundle")
        records[name] = record
        receipt_hashes[name] = sha
    if set(records) != ids or len(records) != 6:
        raise ValueError(f"required six distinct holdout worlds, received {len(records)}")
    for family in FAMILIES:
        subset = [r for r in records.values() if r["family"] == family]
        if len(subset) != 2:
            raise ValueError("holdout lacks two independent registered worlds in each family")
        if sorted(x["holdoutOrder"] for x in subset) != [["fixed", "frozen"], ["frozen", "fixed"]]:
            raise ValueError("ABAB counterbalanced policy execution order is missing")

    def values(label: str) -> list[float]:
        return [
            float(rec["arms"][label]["bestApprovedSilhouetteIoU"])
            if rec["arms"][label]["bestApprovedSilhouetteIoU"] is not None else -1.0
            for rec in records.values()
        ]

    fixed, learned = values("fixed"), values("frozen")
    median_fixed, median_learned = median(fixed), median(learned)
    delta = median_learned - median_fixed
    failures = {
        label: sum(rec["arms"][label]["hardGateFailureCount"] for rec in records.values())
        for label in ("fixed", "frozen")
    }
    per_family = {}
    for family in FAMILIES:
        subset = [r for r in records.values() if r["family"] == family]
        base = [r["arms"]["fixed"]["bestApprovedSilhouetteIoU"] for r in subset]
        test = [r["arms"]["frozen"]["bestApprovedSilhouetteIoU"] for r in subset]
        # No approved candidate is explicitly worse than any accepted image.
        per_family[family] = {
            "meanFixed": mean(v if v is not None else -1.0 for v in base),
            "meanFrozen": mean(v if v is not None else -1.0 for v in test),
        }
    fixed_evals = [r["arms"]["fixed"]["evaluationsToTarget"] for r in records.values()]
    frozen_evals = [r["arms"]["frozen"]["evaluationsToTarget"] for r in records.values()]
    # Latency parity claims require the SAME successes in both arms, not just
    # the median among whatever easier subset the policy happened to win.
    paired_success = all(a is not None and b is not None for a, b in zip(fixed_evals, frozen_evals))
    reduction = (
        (median(fixed_evals) - median(frozen_evals)) / median(fixed_evals)
        if paired_success else None
    )
    no_hard_gate_regression = failures["frozen"] <= failures["fixed"]
    no_family_regression = all(
        row["meanFrozen"] + .002 >= row["meanFixed"] for row in per_family.values()
    )
    gain_pass = delta >= .01
    parity_pass = abs(delta) <= .002 and reduction is not None and reduction >= .20
    accepted = (gain_pass or parity_pass) and no_hard_gate_regression and no_family_regression
    result = {
        "schemaVersion": 1, "status": "holdout-measured",
        "sourceRegistrationSha256": digest,
        "frozenPolicyDigest": frozen["policyDigest"],
        "worldCount": len(records), "familyCount": len(FAMILIES),
        "policy": frozen["coordinateOrder"], "incumbent": [0, 1],
        "medianFixedBestApprovedIoU": median_fixed,
        "medianFrozenBestApprovedIoU": median_learned,
        "medianIoUDelta": delta,
        "medianEvaluationsReduction": reduction,
        "hardGateFailures": failures,
        "perFamily": per_family,
        "noFamilyRegression": no_family_regression,
        "noHardGateRegression": no_hard_gate_regression,
        "holdoutGateSatisfied": accepted,
        "scientificConclusion": "threshold-met" if accepted else "no-verified-advantage",
        "holdoutReceiptSha256": receipt_hashes,
        "cannotClaim": ["unbiased human-blind test", "real-photo likeness", "cross-hardware latency win",
                        "maintainer acceptance", "production policy safety"],
    }
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with report_file.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--policy", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    try:
        result = aggregate(args.root, args.policy, args.out)
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError) as error:
        print(f"holdout aggregation refused: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": result["status"],
        "holdoutGateSatisfied": result["holdoutGateSatisfied"],
        "scientificConclusion": result["scientificConclusion"],
        "medianIoUDelta": result["medianIoUDelta"],
        "noHardGateRegression": result["noHardGateRegression"],
        "noFamilyRegression": result["noFamilyRegression"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
