#!/usr/bin/env python3
"""Author a traceable manual proxy for a CC BY-SA 3.0 open-box photograph.

A real photograph is used for comparative visual evaluation, but panel
dimensions, camera, materials and fold angles are manually authored.
This is not automatic image-to-3D reconstruction or a claimed image fit.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage3_build"))
from generate_threejs_factory import generate  # noqa: E402


def spec_for_photo() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "template.json"
        subprocess.run(
            [sys.executable, str(ROOT / "forge" / "stage2_spec" / "new_sculpt_spec.py"),
             "Open Folding Carton", "--out", str(path)],
            capture_output=True, check=True, text=True,
        )
        spec = json.loads(path.read_text(encoding="utf-8"))

    prototype = spec["componentTree"][0]
    def panel(id, parent, xyz, dims, hinge=None):
        c = copy.deepcopy(prototype)
        c.update({
            "id": id, "name": id.replace("-", " ").title(),
            "parent": parent, "level": "macro", "primitive": "box",
            "role": "panel",
            "topologyClass": "assembled-solid",
            "topologyRationale": "Rectangular sheet of cardboard with visible crease.",
            "geometryDescriptor": {},
            "dimensions": {"width": dims[0], "height": dims[1], "depth": dims[2]},
            "transform": {"position": xyz, "rotation": [0, 0, 0], "scale": dims},
        })
        c.pop("attachment", None)
        c.pop("hinge", None)
        if hinge is not None:
            c["hinge"] = hinge
        return c

    def joint(a, b):
        return {"axisStart": a, "axisEnd": b, "restAngleDeg": 0}

    spec["componentTree"] = [
        panel("floor", None, [0, 0, 0], [2.0, 0.05, 1.5]),
        panel("back-flap", "floor", [0, 0, -1.20], [2.0, 0.035, 0.90],
              joint([-1, 0, -0.75], [1, 0, -0.75])),
        panel("front-flap", "floor", [0, 0, 1.04], [2.0, 0.035, 0.58],
              joint([-1, 0, 0.75], [1, 0, 0.75])),
        panel("left-flap", "floor", [-1.42, 0, 0], [0.84, 0.035, 1.5],
              joint([-1, 0, -0.75], [-1, 0, 0.75])),
        panel("right-flap", "floor", [1.44, 0, 0], [0.88, 0.035, 1.5],
              joint([1, 0, -0.75], [1, 0, 0.75])),
    ]
    return spec


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: emit_hinge_photo_fixture.py output.ts")
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    source = generate(spec_for_photo(), "blockout")
    output.write_text(source, encoding="utf-8")
    print("Emitted real-photo manual-proxy factory:", len(source), "characters")


if __name__ == "__main__":
    main()
