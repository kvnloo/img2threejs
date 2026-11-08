#!/usr/bin/env python3
"""Verify STL export round-trips through independent OpenSCAD geometry import.

Optional CI smoke; OpenSCAD must be installed separately. This is not a
3D-print slicer test, G-code validation, or proof of wall thickness.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "forge" / "stage3_build" / "print_export.py"
VERTICES = (
    (0, 0, 0), (1, 0, 0), (1, 2, 0), (0, 2, 0),
    (0, 0, 3), (1, 0, 3), (1, 2, 3), (0, 2, 3),
)
FACES = (
    (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
    (0, 1, 5), (0, 5, 4), (3, 7, 6), (3, 6, 2),
    (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
)
VERTEX_PATTERN = re.compile(r"^\s*vertex\s+(\S+)\s+(\S+)\s+(\S+)\s*$", re.MULTILINE)


def measure_imported_stl(path: Path) -> tuple[tuple[float, float, float], float, int]:
    """Independently measure OpenSCAD ASCII STL, not the exporter report."""
    positions = [
        tuple(map(float, match))
        for match in VERTEX_PATTERN.findall(path.read_text(encoding="ascii"))
    ]
    if not positions or len(positions) % 3:
        raise AssertionError("OpenSCAD produced no valid ASCII STL triangles")
    if not all(math.isfinite(v) for p in positions for v in p):
        raise AssertionError("OpenSCAD produced non-finite coordinates")
    extents = tuple(
        max(p[axis] for p in positions) - min(p[axis] for p in positions)
        for axis in range(3)
    )
    anchor = positions[0]

    def shift(point):
        return tuple(point[i] - anchor[i] for i in range(3))

    def det(a, b, c):
        return (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        )

    volume = math.fsum(
        det(shift(a), shift(b), shift(c)) / 6.0
        for a, b, c in zip(positions[::3], positions[1::3], positions[2::3])
    )
    return extents, volume, len(positions) // 3


def main() -> int:
    openscad = shutil.which("openscad")
    if not openscad:
        print("OpenSCAD is required for this optional smoke", file=sys.stderr)
        return 2
    if not EXPORTER.is_file():
        print("Run from an img2threejs checkout", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="img2-print-openscad-") as directory:
        root = Path(directory)
        source, original, report, script, roundtrip = (
            root / "meshes.json", root / "model.stl", root / "report.json",
            root / "import.scad", root / "imported.stl",
        )
        source.write_text(json.dumps({
            "coordinateSpace": "world", "incomplete": False,
            "meshes": [{"name": "test-box", "vertices": VERTICES, "indices": FACES}],
        }), encoding="utf-8")
        export = subprocess.run(
            [sys.executable, str(EXPORTER), str(source), "--out", str(original),
             "--report", str(report), "--longest-edge-mm", "60"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if export.returncode != 0:
            raise AssertionError("STL export rejected closed box: " + export.stderr[-1500:])
        receipt = json.loads(report.read_text(encoding="utf-8"))
        if receipt.get("printable") is not True or receipt.get("written") is not True:
            raise AssertionError("Exporter did not write a printable STL")
        script.write_text('import("model.stl", convexity=10);\n', encoding="utf-8")
        checked = subprocess.run(
            [openscad, "--export-format", "asciistl", "-o", str(roundtrip), str(script)],
            cwd=root, capture_output=True, text=True, timeout=60, check=False,
        )
        if checked.returncode != 0:
            raise AssertionError("OpenSCAD rejected generated STL: " + checked.stderr[-1500:])
        if not roundtrip.is_file() or not roundtrip.stat().st_size:
            raise AssertionError("OpenSCAD imported no geometry")
        extents, volume, triangles = measure_imported_stl(roundtrip)
        if not all(
            math.isclose(actual, expected, rel_tol=1e-5, abs_tol=1e-4)
            for actual, expected in zip(extents, (20.0, 40.0, 60.0))
        ):
            raise AssertionError(f"OpenSCAD changed geometry dimensions: {extents}")
        if not math.isclose(volume, 20.0 * 40.0 * 60.0, rel_tol=1e-5):
            raise AssertionError(f"OpenSCAD changed enclosed volume: {volume}")
        if triangles < 12:
            raise AssertionError(f"OpenSCAD emitted too few triangles: {triangles}")
        print(json.dumps({
            "result": "pass", "consumer": "OpenSCAD",
            "triangles": triangles, "sizeMm": extents, "volumeMm3": volume,
            "limit": "not slicer/G-code or real-print acceptance",
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
