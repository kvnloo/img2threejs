#!/usr/bin/env python3
"""Verify browser-exported world meshes through native geometry and print gates."""
from __future__ import annotations

import argparse
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "forge" / "stage3_build" / "print_export.py"
GEOMETRY = ROOT / "forge" / "stage4_review" / "self_intersection.py"


def call(*arguments: str, exit_code: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run([sys.executable, *arguments], capture_output=True, text=True)
    assert result.returncode == exit_code, (
        f"{arguments}: expected {exit_code}, got {result.returncode}\n"
        f"stderr={result.stderr}\nstdout={result.stdout}")
    return result


def verify_case(folder: Path, name: str, shells: int, triangles: int, volume: float) -> dict:
    receipt = folder / f"{name}.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["coordinateSpace"] == "world"
    assert payload["rootSource"] == "explodeRoot"
    assert payload["sceneRootOptIn"] is False
    assert payload["incomplete"] is False
    assert len(payload["meshes"]) == shells
    assert payload["skippedMeshes"] == []
    assert (folder / f"{name}.png").stat().st_size > 1000

    call(str(GEOMETRY), str(receipt), "--json")
    stl = folder / f"{name}.stl"
    obj = folder / f"{name}.obj"
    report_path = folder / f"{name}-print-report.json"
    r = call(str(EXPORTER), str(receipt), "--out", str(stl),
             "--longest-edge-mm", "80", "--report", str(report_path), "--json")
    report = json.loads(r.stdout)
    assert report["watertight"] and report["printable"] and report["written"], report
    assert report["shellCount"] == shells and report["sourceMeshCount"] == shells
    assert report["triangleCount"] == triangles, report
    assert report["insideOutShellCount"] == 0
    assert report["zeroVolumeShellCount"] == 0
    assert math.isclose(report["volume"], volume, rel_tol=1e-5), report
    assert math.isclose(max(report["bounds"]["size"]), 80.0, abs_tol=1e-6), report

    binary = stl.read_bytes()
    assert len(binary) == 84 + triangles * 50, (name, len(binary))
    assert struct.unpack_from("<I", binary, 80)[0] == triangles
    for i in range(triangles):
        facet = struct.unpack_from("<12f", binary, 84 + i * 50)
        assert all(map(math.isfinite, facet))
        assert math.hypot(*facet[:3]) > 0.5, facet
    call(str(EXPORTER), str(receipt), "--out", str(obj), "--longest-edge-mm", "80")
    lines = obj.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("v ") for line in lines) == report["vertexCount"]
    assert sum(line.startswith("f ") for line in lines) == triangles
    return {"case": name, "shells": shells, "triangles": triangles,
            "volumeMm3": report["volume"], "stlBytes": len(binary)}


def check_negative_controls(folder: Path) -> None:
    valid = json.loads((folder / "box.json").read_text(encoding="utf-8"))
    mutations = {
        "incomplete": {**valid, "incomplete": True},
        "local-space": {**valid, "coordinateSpace": "local"},
        "active-skipped": {**valid, "skippedMeshes": [
            {"name": "arm", "reason": "skinned-mesh"}]},
    }
    for label, payload in mutations.items():
        receipt = folder / f"unsafe-{label}.json"
        artifact = folder / f"unsafe-{label}.stl"
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        call(str(EXPORTER), str(receipt), "--out", str(artifact),
             "--allow-open", exit_code=2)
        assert not artifact.exists()
    assert not (folder / "partial.json").exists()
    partial = json.loads((folder / "partial.json.incomplete.json").read_text(encoding="utf-8"))
    assert partial["incomplete"] is True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True, type=Path)
    folder = parser.parse_args().evidence_dir.resolve()
    box = verify_case(folder, "box", 1, 12, 128000.0)
    instances = verify_case(folder, "instances", 2, 24, 8192.0)
    check_negative_controls(folder)
    result = {"kind": "real-threejs-browser-to-print",
              "cases": [box, instances], "negativeControls": 3,
              "slicerVerified": False, "realPhotoFidelityVerified": False,
              "note": "Browser WebGL to scoped world-space meshes, integrity gate, binary STL/OBJ; "
                      "neither physical slicing nor photo reconstruction."}
    (folder / "integration-report.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
