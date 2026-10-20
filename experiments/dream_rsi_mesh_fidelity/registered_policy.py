#!/usr/bin/env python3
"""Freeze a train-only coordinate-priority policy before reserved holdout worlds.

Input MUST be actual native Divine Eye observation receipts, measured and
published by registered_multifamily.score_world. Training sees 12 worlds;
validation sees six additional worlds solely to decide no-regression.
Holdout worlds cannot appear in either input, and the frozen order is hashed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median
import sys
from typing import Any

from registered_multifamily import (
    FAMILIES, REQUIRED_SPLITS, VARIANT_ORDER,
    _canonical, parameter_variants, registration,
)

BUDGET = 3
FIXED = (0, 1)
SHA256_KEYS = ("pngSha256", "specSha256")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def verify_report(file: Path, *, split: str, registry: dict[str, Any], digest: str) -> dict[str, Any]:
    """Do not trust a synthetic/truncated/browser-incomplete status receipt."""
    data = json.loads(file.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in registry["worlds"]}
    if not isinstance(data, dict) or data.get("status") != "native-browser-measured":
        raise ValueError("non-native or incomplete training/validation result")
    world_id = data.get("worldId")
    if world_id not in by_id or by_id[world_id]["split"] != split or data.get("split") != split:
        raise ValueError("policy input includes an unknown or non-allowed split world")
    world = by_id[world_id]
    if data.get("family") != world["family"] or data.get("sourceRegistrationSha256") != digest:
        raise ValueError("policy input disagrees with frozen registration/family")
    if data.get("trainingEligible") is not (split == "train"):
        raise ValueError("policy input training eligibility label is inconsistent")
    if data.get("photographClaim") is not False or data.get("learnedPolicyClaim") is not False:
        raise ValueError("policy input falsely asserts learned/photographic provenance")
    if not _is_sha(data.get("sourceFixtureSha256")) or not _is_sha(data.get("referencePngSha256")):
        raise ValueError("unverified source/target evidence hashes")
    observed = data.get("observed")
    if not isinstance(observed, dict) or tuple(observed) != VARIANT_ORDER:
        raise ValueError("policy requires exactly six native root-neighborhood observations")
    expected = parameter_variants(world)
    for name, record in observed.items():
        if not isinstance(record, dict) or record.get("parameters") != expected[name]:
            raise ValueError("reported candidate geometry changed from registration")
        if not all(_is_sha(record.get(key)) for key in SHA256_KEYS):
            raise ValueError("missing independently verified screenshot/spec hash")
        for field in ("fidelity", "silhouetteIoU"):
            val = record.get(field)
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or not 0 <= val <= 1:
                raise ValueError("native signal invalid or non-finite")
        failures = record.get("hardGateFailures")
        if not isinstance(failures, list) or any(not isinstance(x, str) for x in failures):
            raise ValueError("invalid hard gate receipt")
        # Core fit accepts omitted action/verdict for backwards compatibility.
        # A preregistered *native-browser* observation must contain both
        # explicit review decisions, or a truncated receipt can manufacture
        # an approved result simply by omitting them.
        action, verdict = record.get("action"), record.get("verdict")
        if not isinstance(action, str) or not action or not isinstance(verdict, str) or not verdict:
            raise ValueError("native review action and verdict are required for policy evidence")
        approved = not failures and action == "continue" and verdict == "pass"
        if record.get("approved") is not approved:
            raise ValueError("native approval result misreported in policy input")
    if observed["target"]["silhouetteIoU"] < 0.999:
        raise ValueError("reference fails native self-comparison sanity")
    return data


def collect(root: Path, split: str, registry: dict[str, Any], digest: str) -> tuple[dict[str, Any], dict[str, str]]:
    expected = {row["id"] for row in registry["worlds"] if row["split"] == split}
    found: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    for file in sorted(root.rglob("observations.json")):
        data = verify_report(file, split=split, registry=registry, digest=digest)
        key = data["worldId"]
        if key in found:
            raise ValueError("duplicate native observation receipt for one registered world")
        found[key] = data
        hashes[key] = _sha256(file)
    if set(found) != expected or len(found) != REQUIRED_SPLITS[split]:
        raise ValueError(
            f"need exactly {len(expected)} separate {split} world receipts, "
            f"found {len(found)}"
        )
    return found, hashes


def observed_best(report: dict[str, Any], order: tuple[int, int]) -> tuple[float, int, int | None]:
    """Apply policy to *recorded* root neighborhood only; no counterfactuals."""
    visits = ("root", f"c{order[0]}-minus", f"c{order[0]}-plus")
    assert len(visits) == BUDGET
    rows = report["observed"]
    clean = [(position, rows[name]["silhouetteIoU"]) for position, name
             in enumerate(visits, start=1) if rows[name]["approved"]]
    hard_failures = sum(bool(rows[name]["hardGateFailures"]) for name in visits)
    reached = next((position for position, value in clean if value >= 0.96), None)
    return max((value for _, value in clean), default=-1.0), hard_failures, reached


def train_priority(train: dict[str, Any]) -> tuple[int, int]:
    """Train on fully accepted root and probe outcomes only.

    No pending-review, hard-gate-failed, or validation/holdout result may
    improve the learned direction. Unusable coordinate observations score
    -1 for that world, conservatively penalizing missing approvals.
    """
    gains: dict[int, list[float]] = {0: [], 1: []}
    for report in train.values():
        records = report["observed"]
        root = records["root"]
        for coordinate in (0, 1):
            approved = [
                records[f"c{coordinate}-{direction}"]["silhouetteIoU"]
                for direction in ("minus", "plus")
                if records[f"c{coordinate}-{direction}"]["approved"]
            ]
            gain = max(approved) - root["silhouetteIoU"] if root["approved"] and approved else -1.0
            gains[coordinate].append(gain)
    if any(len(values) != REQUIRED_SPLITS["train"] for values in gains.values()):
        raise ValueError("training coverage incomplete")
    return tuple(sorted(gains, key=lambda i: (-mean(gains[i]), i)))  # type: ignore[return-value]


def summarize(reports: dict[str, Any], order: tuple[int, int]) -> dict[str, Any]:
    results = {name: observed_best(report, order) for name, report in reports.items()}
    per_family: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        subset = [metrics for wid, metrics in results.items()
                  if reports[wid]["family"] == family]
        per_family[family] = {
            "meanBestApprovedIoU": round(mean(m[0] for m in subset), 6),
            "hardGateCount": sum(m[1] for m in subset),
            "cleanWorldCount": sum(m[0] >= 0 for m in subset),
        }
    bests = [metrics[0] for metrics in results.values()]
    clean_times = [metrics[2] for metrics in results.values() if metrics[2] is not None]
    return {
        "evaluationsPerWorld": BUDGET,
        "worldCount": len(results),
        "medianBestApprovedIoU": round(median(bests), 6),
        "meanBestApprovedIoU": round(mean(bests), 6),
        "hardGateCount": sum(metrics[1] for metrics in results.values()),
        "cleanWorldCount": sum(metrics[0] >= 0 for metrics in results.values()),
        "targetHits": len(clean_times),
        "medianEvaluationsToTarget": median(clean_times) if clean_times else None,
        "families": per_family,
    }


def freeze_policy(train_root: Path, validation_root: Path, out_file: Path) -> dict[str, Any]:
    registry, digest = registration()
    train, train_hashes = collect(train_root, "train", registry, digest)
    validation, validation_hashes = collect(validation_root, "validation", registry, digest)
    if set(train) & set(validation):
        raise ValueError("training/validation worlds overlap")
    learned = train_priority(train)
    candidate = summarize(validation, learned)
    incumbent = summarize(validation, FIXED)
    # No policy learning from validation: validation ONLY gates adoption,
    # with a conservative family-by-family veto against meaningful regression.
    passes = (
        candidate["medianBestApprovedIoU"] + .002 >= incumbent["medianBestApprovedIoU"]
        and candidate["hardGateCount"] <= incumbent["hardGateCount"]
        and all(
            candidate["families"][family]["meanBestApprovedIoU"] + .002
            >= incumbent["families"][family]["meanBestApprovedIoU"]
            for family in FAMILIES
        )
    )
    final = learned if passes else FIXED
    lock = {
        "schema": "rsi-multifamily-policy-freeze-v1",
        "registrationSha256": digest,
        "trainingWorldIds": sorted(train),
        "validationWorldIds": sorted(validation),
        "trainingReceiptSha256": train_hashes,
        "validationReceiptSha256": validation_hashes,
        "candidateOrder": list(learned),
        "coordinateOrder": list(final),
        "validationPassed": passes,
        "validation": {"candidate": candidate, "incumbent": incumbent},
        "holdoutOpened": False,
        "holdoutObserved": False,
        "trainingOnlyPolicy": True,
        "photoFidelityClaim": False,
        "holdoutPerformanceClaim": False,
        "review": "NO held-out world observed during training or validation; no real photo fidelity claimed",
    }
    lock["policyDigest"] = hashlib.sha256(_canonical(lock)).hexdigest()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("x", encoding="utf-8") as f:
        f.write(json.dumps(lock, indent=2, allow_nan=False) + "\n")
    return lock


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--train-root", type=Path, required=True)
    ap.add_argument("--validation-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        lock = freeze_policy(args.train_root, args.validation_root, args.out)
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        print(f"RSI policy freeze refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "frozen": True, "registrationSha256": lock["registrationSha256"],
        "candidateOrder": lock["candidateOrder"], "frozenOrder": lock["coordinateOrder"],
        "validationPassed": lock["validationPassed"], "policyDigest": lock["policyDigest"],
        "holdoutOpened": lock["holdoutOpened"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
