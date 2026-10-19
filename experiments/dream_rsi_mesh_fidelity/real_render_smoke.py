#!/usr/bin/env python3
"""Single-world *real Three.js* / Divine Eye preflight; not a holdout experiment.

Reference and candidates are generated from the same immutable public test fixture.
This deliberately makes NO claim about learned order, cross-family generalization,
or photo fidelity. Fail closed when browser images or native scores are missing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "forge/tests/fixtures/reference_target_conformance_spec.json"
GENERATOR = ROOT / "forge/stage3_build/generate_threejs_factory.py"
CAMERA = {"position": [1.1, 0.55, 1.8], "target": [0, 0.16, 0], "fovDegrees": 35}
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
VIEWER = """import * as THREE from 'three';
import { createTradeItHardCaseModel } from './model.ts';
const scene = new THREE.Scene();
const model = createTradeItHardCaseModel();
scene.add(model);
const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 30);
camera.position.set(1.1, 0.55, 1.8);
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


def prepare(out: Path) -> None:
    if not FIXTURE.exists() or not GENERATOR.exists():
        raise RuntimeError("canonical source fixture/generator missing")
    out.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if fixture.get("targetName") != "TradeIt Hard Case":
        raise RuntimeError("frozen fixture identity changed: refuse cross-fixture benchmark")
    generated = []
    for variant, (sx, sz) in PARAMETERS.items():
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
    receipt = {"schemaVersion": 1, "status": "prepared-not-rendered",
               "fixture": str(FIXTURE.relative_to(ROOT)),
               "fixtureSha256": sha256(FIXTURE),
               "source": "actual generate_threejs_factory.py --pass-id blockout",
               "render": "headless Chromium + three.js (not a numeric stand-in)",
               "camera": CAMERA, "size": IMAGE_SIZE,
               "gitSha": os.environ.get("GITHUB_SHA"),
               "variants": generated, "measuredFidelity": None}
    (out / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def score(out: Path) -> None:
    sys.path.insert(0, str(ROOT / "forge/stage4_review"))
    from divine_eye import evaluate  # noqa: E402
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "prepared-not-rendered":
        raise RuntimeError("unexpected or already-scored manifest")
    if sha256(FIXTURE) != manifest.get("fixtureSha256"):
        raise RuntimeError("source fixture hash drift")
    reference = out / "target/render.png"
    if not reference.is_file():
        raise RuntimeError("missing true browser-rendered target")
    scored = {}
    for item in manifest["variants"]:
        name = item["name"]
        image = out / name / "render.png"
        if not image.is_file() or image.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("missing or invalid browser PNG: " + name)
        wh = struct.unpack(">II", image.read_bytes()[16:24])
        if wh != (IMAGE_SIZE, IMAGE_SIZE):
            raise RuntimeError("wrong browser PNG dimensions: " + name)
        if sha256(out / name / "model.ts") != item["generatedTypeScriptSha256"]:
            raise RuntimeError("generated model changed after manifest preparation")
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
    args = ap.parse_args()
    if args.phase == "prepare":
        prepare(args.out.resolve())
    else:
        score(args.out.resolve())


if __name__ == "__main__":
    main()
