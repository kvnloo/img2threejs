#!/usr/bin/env python3
"""Compare baseline vs reconstruction-evidence shadow runs for exact behavioral parity."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence


_RECEIPT_KEY = "fitEvidenceBundle"


def _without_evidence_receipts(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_evidence_receipts(item)
            for key, item in value.items()
            if key != _RECEIPT_KEY
        }
    if isinstance(value, list):
        return [_without_evidence_receipts(item) for item in value]
    return deepcopy(value)


def _candidate_sequence(payload: Mapping[str, Any]) -> list[list[float]]:
    results = payload.get("divineEyeResults")
    if not isinstance(results, list):
        raise ValueError("divineEyeResults must be an array")
    sequence: list[list[float]] = []
    for index, result in enumerate(results):
        if not isinstance(result, Mapping):
            raise ValueError(f"divineEyeResults[{index}] must be an object")
        candidate = result.get("fitCandidateParameters")
        if not isinstance(candidate, list):
            raise ValueError(f"divineEyeResults[{index}].fitCandidateParameters must be an array")
        sequence.append(candidate)
    return sequence


def _evidence_receipts(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    results = payload.get("divineEyeResults")
    if not isinstance(results, list):
        raise ValueError("divineEyeResults must be an array")
    receipts: list[Mapping[str, Any]] = []
    for index, result in enumerate(results):
        if not isinstance(result, Mapping):
            raise ValueError(f"divineEyeResults[{index}] must be an object")
        receipt = result.get(_RECEIPT_KEY)
        if not isinstance(receipt, Mapping):
            raise ValueError(f"divineEyeResults[{index}].{_RECEIPT_KEY} must be an object")
        receipts.append(receipt)
    return receipts


def compare_shadow_runs(
    baseline: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_sequence = _candidate_sequence(baseline)
    evidence_sequence = _candidate_sequence(evidence)
    receipts = _evidence_receipts(evidence)

    baseline_has_receipt = any(
        isinstance(result, Mapping) and _RECEIPT_KEY in result
        for result in baseline.get("divineEyeResults", [])
    )
    if baseline_has_receipt:
        raise ValueError("baseline run unexpectedly contains reconstruction evidence receipts")

    if not receipts:
        raise ValueError("evidence run must contain at least one candidate receipt")

    first_receipt = receipts[0]
    if any(receipt != first_receipt for receipt in receipts[1:]):
        raise ValueError("evidence receipt changed within one fitting run")

    stripped_baseline = _without_evidence_receipts(baseline)
    stripped_evidence = _without_evidence_receipts(evidence)
    parity = stripped_baseline == stripped_evidence

    baseline_fit = baseline.get("fitResult")
    evidence_fit = evidence.get("fitResult")
    if not isinstance(baseline_fit, Mapping) or not isinstance(evidence_fit, Mapping):
        raise ValueError("fitResult must be an object in both runs")

    return {
        "schemaVersion": 1,
        "kind": "img2threejs.reconstruction-evidence-shadow-parity",
        "parity": parity,
        "candidateSequenceParity": baseline_sequence == evidence_sequence,
        "candidateCount": len(baseline_sequence),
        "baseline": {
            "bestObjectiveScore": baseline.get("bestObjectiveScore"),
            "bestRawFidelity": baseline.get("bestRawFidelity"),
            "evaluations": baseline_fit.get("evaluations"),
            "parameters": baseline_fit.get("parameters"),
        },
        "evidence": {
            "bestObjectiveScore": evidence.get("bestObjectiveScore"),
            "bestRawFidelity": evidence.get("bestRawFidelity"),
            "evaluations": evidence_fit.get("evaluations"),
            "parameters": evidence_fit.get("parameters"),
            "bundleId": first_receipt.get("bundleId"),
            "manifestSha256": first_receipt.get("manifestSha256"),
        },
    }


def _load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = compare_shadow_runs(_load_json(args.baseline), _load_json(args.evidence))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        state = "PASS" if report["parity"] else "FAIL"
        print(
            f"{state}: candidates={report['candidateCount']} "
            f"bundle={report['evidence']['bundleId']}"
        )
    return 0 if report["parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
