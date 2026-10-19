#!/usr/bin/env python3
"""Real on-demand Chromium-render A/B for deterministic coordinate-order fitting.

Each fit callback launches Chromium and captures a new PNG; it cannot return
the pre-rendered reference-world candidates. This is one procedural target
and one previously inspected neighborhood, NOT a learned-policy holdout.
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
CAPTURE = Path(__file__).resolve().parent / "real_browser_capture.mjs"
sys.path.insert(0, str(ROOT))
from forge.stage4_review.fit_params import FitConfig, FitInputError, fit_against_divine_eye  # noqa: E402
from forge.stage4_review._fit_divine_eye import is_approved_divine_eye_result  # noqa: E402
from forge.stage4_review.divine_eye import evaluate  # noqa: E402
from real_render_smoke import FIXTURE, IMAGE_SIZE, NEIGHBORHOODS, sha256, verify_browser_receipt  # noqa: E402

BUDGET = 3
ORDERS = (
    ("index-order", (0, 1), ("root", "c0-minus", "c0-plus")),
    ("reverse-order", (1, 0), ("root", "c1-minus", "c1-plus")),
)


def resolve_candidate(values: tuple[float, ...], presets: dict[str, list[float]]) -> str:
    """Select only exact known spec vectors; no guessed counterfactual render."""
    if len(values) != 2 or any(not isinstance(v, (float, int)) or
                               isinstance(v, bool) or not math.isfinite(v) for v in values):
        raise ValueError("live fitting requires two finite parameter coordinates")
    names = [
        name for name, authored in presets.items() if name != "target"
        and len(authored) == 2
        and all(abs(v - a) <= 1e-9 for v, a in zip(values, authored))
    ]
    if len(names) != 1:
        raise ValueError("fitter requested a non-authored or ambiguous geometry candidate")
    return names[0]


def validated_world(out: Path) -> tuple[dict[str, Any], dict[str, list[float]], Path]:
    """Refuse stale preparation or a reference from another capture session."""
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    measured = json.loads((out / "results.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("status") != "prepared-not-rendered":
        raise ValueError("prepared real-render manifest is missing")
    if not isinstance(measured, dict) or measured.get("status") != "browser-render-and-native-divine-eye-measured":
        raise ValueError("verified real-render score result is missing")
    cohort = manifest.get("neighborhood")
    if cohort not in NEIGHBORHOODS or manifest.get("parameters") != NEIGHBORHOODS[cohort]:
        raise ValueError("unknown or modified research cohort")
    if measured.get("neighborhood") != cohort or measured.get("gitSha") != manifest.get("gitSha"):
        raise ValueError("render provenance/cohort mismatch")
    if sha256(FIXTURE) != manifest.get("fixtureSha256"):
        raise ValueError("procedural reference fixture SHA drift")
    params = NEIGHBORHOODS[cohort]
    variants = manifest.get("variants")
    if not isinstance(variants, list) or [x.get("name") for x in variants
                                         if isinstance(x, dict)] != list(params):
        raise ValueError("candidate list drifted since preparation")
    if len(variants) != len(params):
        raise ValueError("invalid or duplicate candidate manifest entries")
    for item in variants:
        name = item["name"]
        if sha256(out / name / "spec.json") != item.get("specSha256"):
            raise ValueError("frozen geometry spec changed: " + name)
        if sha256(out / name / "model.ts") != item.get("generatedTypeScriptSha256"):
            raise ValueError("generated Three.js model changed: " + name)
        verify_browser_receipt(out / name, name)
    target = out / "target" / "render.png"
    if not target.is_file() or sha256(target) != measured["measuredFidelity"]["target"]["imageSha256"]:
        raise ValueError("target/reference image is stale or missing")
    return manifest, params, target


def run_live(out: Path) -> dict[str, Any]:
    manifest, params, reference = validated_world(out)
    world_dir = out / "worlds"
    world_dir.mkdir(exist_ok=True)
    report_file = world_dir / "live-browser-budget-ab.json"
    if report_file.exists():
        raise ValueError("live-budget receipt already exists; refuse a hidden second run")
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "status": "in-progress",
        "kind": "real-on-demand-webgl2-chromium-budget-ab",
        "sourceGitSha": manifest["gitSha"],
        "fixtureSha256": manifest["fixtureSha256"],
        "cohort": manifest["neighborhood"],
        "referencePngSha256": sha256(reference),
        "budgetedBrowserRendersPerOrder": BUDGET,
        "referenceRenderExcludedFromBudget": True,
        "preRenderedCandidateReuse": False,
        "baselineMethod": "fixed-index order versus deterministic reverse order",
        "learnedPolicyClaim": False,
        "holdoutClaim": False,
        "photographClaim": False,
        "policies": {},
    }
    report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    root = params["root"]
    steps = (params["c0-plus"][0] - root[0], params["c1-plus"][1] - root[1])
    if any(step <= 0 or not math.isfinite(step) for step in steps):
        raise ValueError("invalid frozen step widths")
    bounds = tuple((v - 2 * step, v + 2 * step) for v, step in zip(root, steps))

    for label, order, expected in ORDERS:
        calls: list[dict[str, Any]] = []
        started = time.perf_counter()

        def render_live(values: tuple[float, ...]) -> Path:
            name = resolve_candidate(values, params)
            if len(calls) >= BUDGET:
                raise RuntimeError("live browser render budget exceeded")
            tag = f"live-{label}-{len(calls) + 1}"
            image = out / name / f"{tag}.png"
            receipt = out / name / f"{tag}.json"
            if image.exists() or receipt.exists():
                raise RuntimeError("live render was previously captured: " + tag)
            # Record an attempted browser invocation before doing expensive work.
            attempt: dict[str, Any] = {"variant": name, "tag": tag, "status": "started"}
            calls.append(attempt)
            invoked = time.perf_counter()
            proc = subprocess.run(
                ["node", str(CAPTURE), str(out), "--variant", name, "--tag", tag],
                cwd=ROOT, capture_output=True, text=True, check=False, timeout=180,
                env=os.environ.copy(),
            )
            attempt["wallSeconds"] = round(time.perf_counter() - invoked, 3)
            if proc.returncode != 0:
                attempt["status"] = "failed"
                raise RuntimeError(f"Chromium capture failed for {tag} with exit {proc.returncode}")
            # The real-browser runner must identify precisely which fresh
            # capture it made. Do not reuse previously measured image evidence.
            events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip().startswith("{")]
            if len(events) != 1 or events[0].get("variant") != name or events[0].get("captureTag") != tag or events[0].get("liveCapture") is not True:
                raise RuntimeError("browser failed to identify the requested live capture")
            if not image.is_file() or image.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                raise RuntimeError("fresh browser screenshot is missing or invalid")
            if struct.unpack(">II", image.read_bytes()[16:24]) != (IMAGE_SIZE, IMAGE_SIZE):
                raise RuntimeError("live browser screenshot has wrong dimensions")
            verify_browser_receipt(out / name, name, receipt_name=receipt.name)
            browser_receipt = json.loads(receipt.read_text(encoding="utf-8"))
            if browser_receipt.get("variant") != name or browser_receipt.get("captureTag") != tag:
                raise RuntimeError("browser receipt identifies a different candidate")
            attempt["status"] = "captured"
            attempt["pngSha256"] = sha256(image)
            attempt["browserVersion"] = browser_receipt["chromium"]
            return image

        fitted = fit_against_divine_eye(
            root, bounds, render_live, reference, evaluate,
            FitConfig(max_evaluations=BUDGET, coordinate_order=order),
        )
        visited = tuple(row["variant"] for row in calls)
        if visited != expected or fitted.fit_result.evaluations != BUDGET:
            raise RuntimeError(f"live policy candidate dispatch drift in {label}: {visited}")
        if any(row["status"] != "captured" for row in calls):
            raise RuntimeError("incomplete browser render counted as successful")
        clean = [
            result["signals"]["silhouetteIoU"]
            for result in fitted.divine_eye_results
            if is_approved_divine_eye_result(result, FitInputError, "Divine Eye result")
        ]
        for idx, result in enumerate(fitted.divine_eye_results):
            calls[idx]["divineEyeFidelity"] = result["fidelity"]
            calls[idx]["silhouetteIoU"] = result["signals"]["silhouetteIoU"]
            calls[idx]["verdict"] = result["verdict"]
            calls[idx]["hardGateFailures"] = result["hardGateFailures"]
        report["policies"][label] = {
            "coordinateOrder": list(order),
            "wallSeconds": round(time.perf_counter() - started, 3),
            "browserRendersInvoked": len(calls),
            "actualEvaluatorCalls": fitted.fit_result.evaluations,
            "bestCleanSilhouetteIoU": max(clean, default=None),
            "bestAcceptedFidelity": fitted.best_raw_fidelity,
            "result": fitted.fit_result.to_json(),
            "renders": calls,
        }
        report_file.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    report["status"] = "completed"
    report["limitation"] = (
        "one procedural target; post-hoc calibration; not learned/holdout evidence. "
        "Browser launch+TypeScript bundle+capture costs measured per evaluator call."
    )
    report_file.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_live(args.out.expanduser().resolve())
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
        print(f"live-browser budget experiment refused: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": result["status"], "cohort": result["cohort"],
        "policies": {
            label: {
                "browserRendersInvoked": item["browserRendersInvoked"],
                "actualEvaluatorCalls": item["actualEvaluatorCalls"],
                "bestCleanSilhouetteIoU": item["bestCleanSilhouetteIoU"],
                "bestAcceptedFidelity": item["bestAcceptedFidelity"],
                "wallSeconds": item["wallSeconds"],
            }
            for label, item in result["policies"].items()
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
