#!/usr/bin/env python3
"""Produce an identical curve-sweep fixture from baseline and patched generators.

Called only by the opt-in Chromium smoke workflow; the core stays dependency-free.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "forge"), str(ROOT / "forge" / "_shared"),
                str(ROOT / "forge" / "stage2_spec"), str(ROOT / "forge" / "stage3_build"),
                str(ROOT / "forge" / "tests")]
import generate_threejs_factory as patched  # noqa: E402
from test_attachment_does_not_override_primitive import spec_with  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-generator", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    baseline_path = args.baseline_generator.resolve()
    if not baseline_path.is_file():
        parser.error(f"baseline generator missing: {baseline_path}")
    old_spec = importlib.util.spec_from_file_location("baseline_geometry_generator", baseline_path)
    if old_spec is None or old_spec.loader is None:
        parser.error("cannot load baseline generator")
    baseline = importlib.util.module_from_spec(old_spec)
    old_spec.loader.exec_module(baseline)

    spec = spec_with("curve-sweep", "continuous-sculpt")
    spec["componentTree"][1]["geometryDescriptor"] = {
        "curveSweep": {
            "spine": [[-0.48, -0.32, 0], [0.0, 0.44, 0.08], [0.48, -0.20, 0]],
            "crossSection": {
                "points": [[-0.04, -0.04], [0.04, -0.04],
                           [0.04, 0.04], [-0.04, 0.04]],
            },
            "closed": False,
        }
    }
    original = baseline.generate(spec, "blockout")
    candidate = patched.generate(spec, "blockout")
    # The A/B must exercise the same declared geometry and only differ in generator.
    assert "const endpoint_part_1 = makeAttachmentEndpoint(attachment_part_1)" in original
    assert "const endpoint_part_1 = makeAttachmentEndpoint(null)" in candidate
    assert "buildCurveSweepGeometry" in original and "buildCurveSweepGeometry" in candidate
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "before.ts").write_text(original, encoding="utf-8")
    (out / "after.ts").write_text(candidate, encoding="utf-8")
    (out / "fixture.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print("PASS: same spec, two generators; baseline selects endpoint, patch preserves spine")


if __name__ == "__main__":
    main()
