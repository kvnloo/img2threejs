from copy import deepcopy

import pytest

from forge.stage4_review.reconstruction_evidence_ab import compare_shadow_runs


def _run():
    results = [
        {
            "fidelity": 0.5,
            "hardGateFailures": [],
            "fitCandidateParameters": [0.0],
            "fitReferencePng": "reference.png",
            "fitRenderPath": "render-0.0.png",
        },
        {
            "fidelity": 0.9,
            "hardGateFailures": [],
            "fitCandidateParameters": [0.5],
            "fitReferencePng": "reference.png",
            "fitRenderPath": "render-0.5.png",
        },
    ]
    return {
        "fitResult": {
            "parameters": [0.5],
            "bestScore": 0.9,
            "bestObjectiveScore": 0.9,
            "status": "max-iterations",
            "iterations": 1,
            "evaluations": 2,
            "seed": 7,
            "history": [
                {"iteration": 0, "evaluations": 1, "bestScore": 0.5},
                {"iteration": 1, "evaluations": 2, "bestScore": 0.9},
            ],
        },
        "bestObjectiveScore": 0.9,
        "bestRawFidelity": 0.9,
        "divineEyeResults": results,
        "correctionHistory": [
            {"fidelity": 0.5, "divineEye": deepcopy(results[0])},
            {"fidelity": 0.9, "divineEye": deepcopy(results[1])},
        ],
    }


def _with_receipt(payload):
    result = deepcopy(payload)
    receipt = {
        "bundleId": "chair-0123456789abcdef",
        "manifestSha256": "a" * 64,
        "artifacts": [{"role": "depth", "sha256": "b" * 64}],
    }
    for item in result["divineEyeResults"]:
        item["fitEvidenceBundle"] = deepcopy(receipt)
    for item in result["correctionHistory"]:
        item["divineEye"]["fitEvidenceBundle"] = deepcopy(receipt)
    return result


def test_shadow_receipt_only_run_has_exact_behavioral_parity():
    baseline = _run()
    evidence = _with_receipt(baseline)

    report = compare_shadow_runs(baseline, evidence)

    assert report["parity"] is True
    assert report["candidateSequenceParity"] is True
    assert report["candidateCount"] == 2
    assert report["baseline"]["bestObjectiveScore"] == 0.9
    assert report["evidence"]["bundleId"] == "chair-0123456789abcdef"


def test_shadow_gate_detects_candidate_sequence_change():
    baseline = _run()
    evidence = _with_receipt(baseline)
    evidence["divineEyeResults"][1]["fitCandidateParameters"] = [-0.5]

    report = compare_shadow_runs(baseline, evidence)

    assert report["parity"] is False
    assert report["candidateSequenceParity"] is False


def test_shadow_gate_detects_score_change_even_with_same_candidates():
    baseline = _run()
    evidence = _with_receipt(baseline)
    evidence["fitResult"]["bestScore"] = 0.91
    evidence["fitResult"]["bestObjectiveScore"] = 0.91
    evidence["bestObjectiveScore"] = 0.91

    report = compare_shadow_runs(baseline, evidence)

    assert report["parity"] is False
    assert report["candidateSequenceParity"] is True


def test_shadow_gate_requires_stable_receipt_within_run():
    baseline = _run()
    evidence = _with_receipt(baseline)
    evidence["divineEyeResults"][1]["fitEvidenceBundle"]["bundleId"] = "other"

    with pytest.raises(ValueError, match="changed within"):
        compare_shadow_runs(baseline, evidence)


def test_shadow_gate_rejects_receipt_on_baseline():
    baseline = _with_receipt(_run())
    evidence = _with_receipt(_run())

    with pytest.raises(ValueError, match="baseline run unexpectedly"):
        compare_shadow_runs(baseline, evidence)
