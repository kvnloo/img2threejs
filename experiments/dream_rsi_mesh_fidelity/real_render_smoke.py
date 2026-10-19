#!/usr/bin/env python3
"""Single-world *real Three.js* / Divine Eye preflight; not a holdout experiment.

Reference and candidates are generated from the same immutable public test fixture.
This deliberately makes NO claim about learned order, cross-family generalization,
or photo fidelity. Fail closed when browser images or native scores are missing.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "forge/tests/fixtures/reference_target_conformance_spec.json"
GENERATOR = ROOT / "forge/stage3_build/generate_threejs_factory.py"
CAMERA = {"position": [2.2, 1.1, 3.6], "target": [0, 0.16, 0], "fovDegrees": 35}
IMAGE_SIZE = 256
# One frozen *preflight* neighborhood. Train/holdout separation comes later.
PARAMETERS = {
    "target": [1.0, 1.0],
    "root": [0.78, 0.76],
    "c0-minus": [0.64, 0.76],
    "c0-plus": [0.92, 0.76],
    "c1-minus": [0.78, 0.62],
    "c1-plus": [0.78, 0.90],
}
# Separate pre-declared calibration neighborhood. The original remains frozen
# and retained, including its native evaluator low-confidence failures.
CALIBRATED_PARAMETERS = {
    "target": [1.0, 1.0],
    "root": [0.90, 0.94],
    "c0-minus": [0.80, 0.94],
    "c0-plus": [1.00, 0.94],
    "c1-minus": [0.90, 0.88],
    "c1-plus": [0.90, 1.00],
}
NEIGHBORHOODS = {
    "original": PARAMETERS,
    "calibrated": CALIBRATED_PARAMETERS,
}
VIEWER = """import * as THREE from 'three';
import { createTradeItHardCaseModel } from './model.ts';
const scene = new THREE.Scene();
const model = createTradeItHardCaseModel();
scene.add(model);
const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 30);
camera.position.set(2.2, 1.1, 3.6);
camera.lookAt(0, 0.16, 0);
const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: false, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(256, 256);
renderer.setClearColor(0, 0);
document.body.appendChild(renderer.domElement);
const fill = new THREE.AmbientLight(0xffffff, 1.0);
scene.add(fill);
const key = new THREE.DirectionalLight(0xffffff, 2);
key.position.set(2, 3, 4);
scene.add(key);
renderer.render(scene, camera);
const gl = renderer.getContext();
const pixels = new Uint8Array(256 * 256 * 4);
gl.readPixels(0, 0, 256, 256, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
let foreground = 0;
for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 128) foreground += 1;
window.__rsiCapture = { ready: true, coverage: foreground / (256 * 256),
  webgl: String(gl.getParameter(gl.VERSION)), renderer: String(gl.getParameter(gl.RENDERER)) };
"""
HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:transparent}
canvas{display:block;width:256px;height:256px}
</style></head><body><script src="./bundle.js"></script></body></html>
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(out: Path, neighborhood: str = "original") -> None:
    parameters = NEIGHBORHOODS[neighborhood]
    if not FIXTURE.exists() or not GENERATOR.exists():
        raise RuntimeError("canonical source fixture/generator missing")
    out.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if fixture.get("targetName") != "TradeIt Hard Case":
        raise RuntimeError("frozen fixture identity changed: refuse cross-fixture benchmark")
    generated = []
    for variant, (sx, sz) in parameters.items():
        spec = json.loads(json.dumps(fixture))
        if spec["componentTree"][0].get("id") != "root":
            raise RuntimeError("frozen fixture component order changed")
        spec["componentTree"][0]["transform"]["scale"] = [sx, 1.0, sz]
        folder = out / variant
        folder.mkdir(parents=True, exist_ok=True)
        spec_path = folder / "spec.json"
        spec_path.write_text(json.dumps(spec, sort_keys=True), encoding="utf-8")
        model_path = folder / "model.ts"
        run = subprocess.run(
            [sys.executable, str(GENERATOR), str(spec_path), "--out",
             str(model_path), "--pass-id", "blockout", "--force"],
            cwd=ROOT, capture_output=True, text=True,
        )
        if run.returncode:
            raise RuntimeError("native generator rejected " + variant + ": " + run.stderr[:1500])
        (folder / "viewer.ts").write_text(VIEWER, encoding="utf-8")
        (folder / "index.html").write_text(HTML, encoding="utf-8")
        generated.append({"name": variant, "parameters": [sx, sz],
                          "specSha256": sha256(spec_path),
                          "generatedTypeScriptSha256": sha256(model_path)})
    actual_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    expected_head = os.environ.get("SOURCE_HEAD_SHA")
    if expected_head and actual_head != expected_head:
        raise RuntimeError("wrong checked-out source HEAD: " + actual_head + " != " + expected_head)
    receipt = {"schemaVersion": 1, "status": "prepared-not-rendered",
               "fixture": str(FIXTURE.relative_to(ROOT)),
               "fixtureSha256": sha256(FIXTURE),
               "source": "actual generate_threejs_factory.py --pass-id blockout",
               "render": "headless Chromium + three.js (not a numeric stand-in)",
               "camera": CAMERA, "size": IMAGE_SIZE,
               "gitSha": actual_head,
               "neighborhood": neighborhood, "parameters": parameters,
               "variants": generated, "measuredFidelity": None}
    (out / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def verify_browser_receipt(folder: Path, name: str) -> None:
    """Reject stale, failed or unsupported browser captures before scoring.

    A PNG existing on disk is not proof that the actual Three.js renderer
    produced valid pixels. Only the recorded, successful WebGL2 capture from
    the matching run may enter native Divine Eye comparisons.
    """
    try:
        receipt = json.loads((folder / "browser.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"missing or malformed browser capture receipt: {name}") from error
    if not isinstance(receipt, dict):
        raise RuntimeError(f"invalid browser capture receipt: {name}")
    coverage = receipt.get("coverage")
    if (
        receipt.get("ready") is not True
        or receipt.get("errors") != []
        or isinstance(coverage, bool)
        or not isinstance(coverage, (int, float))
        or not math.isfinite(coverage)
        or not 0.02 < coverage < 0.95
        or not isinstance(receipt.get("webgl"), str)
        or not receipt["webgl"].startswith("WebGL 2.0")
        or not isinstance(receipt.get("chromium"), str)
        or not receipt["chromium"]
        or not isinstance(receipt.get("renderer"), str)
        or not receipt["renderer"]
    ):
        raise RuntimeError(f"unverified WebGL2 browser capture: {name}")


def score(out: Path) -> None:
    sys.path.insert(0, str(ROOT / "forge/stage4_review"))
    from divine_eye import evaluate  # noqa: E402
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "prepared-not-rendered":
        raise RuntimeError("unexpected or already-scored manifest")
    if sha256(FIXTURE) != manifest.get("fixtureSha256"):
        raise RuntimeError("source fixture hash drift")
    neighborhood = manifest.get("neighborhood")
    if neighborhood not in NEIGHBORHOODS or manifest.get("parameters") != NEIGHBORHOODS[neighborhood]:
        raise RuntimeError("unknown or altered candidate neighborhood")
    neighborhood_values = NEIGHBORHOODS[neighborhood]
    if [item.get("name") for item in manifest.get("variants", [])] != list(neighborhood_values):
        raise RuntimeError("candidate list drifted from committed neighborhood")
    reference = out / "target/render.png"
    if not reference.is_file():
        raise RuntimeError("missing true browser-rendered target")
    scored = {}
    for item in manifest["variants"]:
        name = item["name"]
        folder = out / name
        # A changed source spec can otherwise masquerade as the immutable
        # reference of an unchanged compiled model. Validate both hashes.
        if sha256(folder / "spec.json") != item["specSha256"]:
            raise RuntimeError("frozen source spec changed after preparation: " + name)
        if sha256(folder / "model.ts") != item["generatedTypeScriptSha256"]:
            raise RuntimeError("generated model changed after preparation: " + name)
        verify_browser_receipt(folder, name)
        image = folder / "render.png"
        if not image.is_file() or image.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("missing or invalid browser PNG: " + name)
        wh = struct.unpack(">II", image.read_bytes()[16:24])
        if wh != (IMAGE_SIZE, IMAGE_SIZE):
            raise RuntimeError("wrong browser PNG dimensions: " + name)
        result = evaluate(reference, image)
        metric = result.get("signals", {}).get("silhouetteIoU")
        if not isinstance(metric, (int, float)) or isinstance(metric, bool) or not 0 <= metric <= 1:
            raise RuntimeError("native evaluator missing silhouette IoU for " + name)
        scored[name] = {"silhouetteIoU": metric, "fidelity": result["fidelity"],
                        "hardGateFailures": result["hardGateFailures"],
                        "imageSha256": sha256(image)}
        (out / name / "divine-eye.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if scored["target"]["silhouetteIoU"] < 0.999:
        raise RuntimeError("a reference compared to itself must have silhouette IoU 1")

    # Exercise the actual bounded fitter against the observed Chromium pixels.
    # Each policy receives exactly root + two proposals (three *evaluator*
    # calls), but all five images were pre-rendered. This is a dispatch/quality
    # preflight, NOT an end-to-end budgeted live-render or learned-policy test.
    sys.path.insert(0, str(ROOT))
    from forge.stage4_review.fit_params import (  # noqa: E402
        FitConfig, FitInputError, fit_against_divine_eye,
    )
    from forge.stage4_review._fit_divine_eye import (  # noqa: E402
        is_approved_divine_eye_result,
    )

    by_vector = {
        tuple(round(float(value), 2) for value in vector): name
        for name, vector in neighborhood_values.items()
        if name != "target"
    }
    if len(by_vector) != len(neighborhood_values) - 1:
        raise RuntimeError("duplicate rounded real-browser fit candidates")
    paired_fits: dict[str, dict[str, object]] = {}
    for label, order, expected in (
        ("index-order", (0, 1), ("root", "c0-minus", "c0-plus")),
        ("reverse-order", (1, 0), ("root", "c1-minus", "c1-plus")),
    ):
        attempted: list[str] = []

        def render_observed(parameters: tuple[float, ...]) -> Path:
            key = tuple(round(value, 2) for value in parameters)
            name = by_vector.get(key)
            if name is None or any(
                abs(value - authored) > 1e-9
                for value, authored in zip(parameters, neighborhood_values[name])
            ):
                raise RuntimeError(f"fit requested unrendered candidate: {key}")
            attempted.append(name)
            return out / name / "render.png"

        root_vector = neighborhood_values["root"]
        steps = (
            neighborhood_values["c0-plus"][0] - root_vector[0],
            neighborhood_values["c1-plus"][1] - root_vector[1],
        )
        if not all(0 < step < 1 for step in steps):
            raise RuntimeError("invalid frozen neighborhood probe step")
        bounds = tuple((value - 2 * step, value + 2 * step)
                       for value, step in zip(root_vector, steps))
        actual_fit = fit_against_divine_eye(
            root_vector,
            bounds,
            render_observed,
            reference,
            evaluate,
            FitConfig(max_evaluations=3, coordinate_order=order),
        )
        if tuple(attempted) != expected or actual_fit.fit_result.evaluations != 3:
            raise RuntimeError(f"real-browser {label} candidate/budget drift: {attempted}")
        clean_iou = []
        for name, observed in zip(attempted, actual_fit.divine_eye_results):
            # Independent re-evaluation must agree with the preflight's native
            # scorer. Neither a synthetic score nor a replay guess may enter.
            if (
                abs(float(observed["fidelity"]) - scored[name]["fidelity"]) > 1e-12
                or observed["hardGateFailures"] != scored[name]["hardGateFailures"]
            ):
                raise RuntimeError(f"native evaluator/provenance drift for {name}")
            if is_approved_divine_eye_result(observed, FitInputError, "Divine Eye result"):
                clean_iou.append(scored[name]["silhouetteIoU"])
        paired_fits[label] = {
            "coordinateOrder": list(order),
            "candidateNames": attempted,
            "candidatePngSha256": [scored[name]["imageSha256"] for name in attempted],
            "actualEvaluatorCalls": actual_fit.fit_result.evaluations,
            "bestCleanSilhouetteIoUInVisitedCandidates": max(clean_iou, default=None),
            "fit": actual_fit.to_json(),
        }
    worlds_dir = out / "worlds"
    worlds_dir.mkdir(exist_ok=True)
    (worlds_dir / "paired-real-fitter.json").write_text(json.dumps({
        "schemaVersion": 1,
        "kind": "real-chromium-image-paired-native-fit-preflight",
        "sourceGitSha": manifest["gitSha"],
        "fixtureSha256": manifest["fixtureSha256"],
        "neighborhood": neighborhood,
        "renderMode": "pre-rendered verified Chromium screenshots (shared candidate pool)",
        "evaluator": "native Divine Eye, re-evaluated per fitter call",
        "evaluationsPerOrder": 3,
        "liveRenderBudgetClaim": False,
        "learnedPolicyClaim": False,
        "holdoutClaim": False,
        "policies": paired_fits,
    }, indent=2) + "\n", encoding="utf-8")
    manifest["pairedNativeFit"] = "worlds/paired-real-fitter.json"

    # Convert only the *observed* browser renders into an exact-support replay world.
    # There is no policy learning, counterfactual prediction, or unseen geometry here.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from replay import Node, World, CoordinatePriorityPolicy, replay  # noqa: E402

    def observed_node(name: str, parent: str | None, coordinate: int | None,
                      direction: int | None, step: float | None) -> Node:
        return Node(
            id=name, parent_id=parent, coordinate=coordinate,
            direction=direction, step=step,
            silhouette_iou=scored[name]["silhouetteIoU"],
            hard_gate_failures=tuple(scored[name]["hardGateFailures"]),
            cost=1,
        )

    world = World(
        id=f"tradeit-case-native-threejs-{neighborhood}-single-root",
        root_id="root",
        nodes=(
            observed_node("root", None, None, None, None),
            observed_node("c0-minus", "root", 0, -1, steps[0]),
            observed_node("c0-plus", "root", 0, +1, steps[0]),
            observed_node("c1-minus", "root", 1, -1, steps[1]),
            observed_node("c1-plus", "root", 1, +1, steps[1]),
        ),
    )
    world.index()  # fail closed on malformed node parents/scores
    worlds_dir = out / "worlds"
    worlds_dir.mkdir(exist_ok=True)
    replay_receipt = {
        "schemaVersion": 1,
        "kind": "observed-browser-world-no-learned-policy",
        "sourceGitSha": manifest["gitSha"],
        "fixtureSha256": manifest["fixtureSha256"],
        "neighborhood": neighborhood,
        "world": asdict(world),
        "renderSha256ByNode": {key: scored[key]["imageSha256"]
                               for key in ("root", "c0-minus", "c0-plus", "c1-minus", "c1-plus")},
        "policyProbe": {
            "fixed-order-budget3": asdict(replay(world, CoordinatePriorityPolicy((0, 1)), budget=3, target_iou=0.96)),
            "reverse-order-budget3": asdict(replay(world, CoordinatePriorityPolicy((1, 0)), budget=3, target_iou=0.96)),
        },
        "claim": "same-world recorded-score replay only; NOT learned or held-out evidence",
    }
    (worlds_dir / "single-world.json").write_text(
        json.dumps(replay_receipt, indent=2) + "\n", encoding="utf-8")
    manifest["observedReplayWorld"] = "worlds/single-world.json"
    manifest["status"] = "browser-render-and-native-divine-eye-measured"
    manifest["measuredFidelity"] = scored
    manifest["limitation"] = ("ONE procedural fixture, ONE starting point, no learned policy, "
                              "no held-out worlds, no source photograph. NOT an A/B claim.")
    (out / "results.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "iou": {k: v["silhouetteIoU"] for k, v in scored.items()}}, sort_keys=True))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase", choices=["prepare", "score"])
    ap.add_argument("out", type=Path)
    ap.add_argument("--neighborhood", choices=tuple(NEIGHBORHOODS), default="original")
    args = ap.parse_args()
    if args.phase == "prepare":
        prepare(args.out.resolve(), args.neighborhood)
    else:
        score(args.out.resolve())


if __name__ == "__main__":
    main()
