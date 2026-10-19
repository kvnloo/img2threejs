"""Reject arithmetic overflow in measured vehicle cross-sections before scoring."""
from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "integrations" / "vehicle_form" / "plan_taper.py"
spec = importlib.util.spec_from_file_location("vehicle_taper_finite", SCRIPT)
assert spec and spec.loader
taper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(taper)


def sections():
    return {
        "schemaVersion": 1,
        "axis": "x", "lateralAxis": "z",
        "reference": {"kind": "measured-top-view", "source": "synthetic sections"},
        "stations": [
            {"id": "front", "x": 0.25, "referenceWidth": 1.0},
            {"id": "center", "x": 1.0, "referenceWidth": 1.0},
            {"id": "rear", "x": 1.75, "referenceWidth": 1.0},
        ],
    }


def receipt(vertices, indices):
    return {
        "coordinateSpace": "world", "incomplete": False,
        "meshes": [{"name": "body", "vertices": vertices, "indices": indices}],
    }


class FiniteMeasurementTest(unittest.TestCase):
    def test_opposite_large_x_positions_cannot_overflow_span(self):
        # Each separate triangle has perfectly finite area, even though their
        # combined world-space longitudinal span overflows binary64.
        vertices = [
            [-1e308, 0, 0], [-1e308, 1, 0], [-1e308, 0, 1],
            [1e308, 0, 0], [1e308, 1, 0], [1e308, 0, 1],
        ]
        with self.assertRaisesRegex(taper.PlanTaperInputError, "non-finite longitudinal"):
            taper.evaluate(receipt(vertices, [0, 1, 2, 3, 4, 5]),
                           sections(), mesh_name="body")

    def test_opposite_large_z_positions_cannot_overflow_width(self):
        # Two finite-area x/y triangles on opposite sides of the same section:
        # zmax-zmin is +inf. NaN-normalizing it must never return passed=true.
        vertices = [
            [0, 0, -1e308], [2, 0, -1e308], [0, 1, -1e308],
            [0, 0, 1e308], [2, 0, 1e308], [0, 1, 1e308],
        ]
        with self.assertRaisesRegex(taper.PlanTaperInputError, "non-finite lateral section width"):
            taper.evaluate(receipt(vertices, [0, 1, 2, 3, 4, 5]),
                           sections(), mesh_name="body")

    def test_cli_fails_closed_without_nan_evidence_or_false_pass(self):
        vertices = [
            [0, 0, -1e308], [2, 0, -1e308], [0, 1, -1e308],
            [0, 0, 1e308], [2, 0, 1e308], [0, 1, 1e308],
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mesh = root / "mesh.json"
            table = root / "table.json"
            mesh.write_text(json.dumps(receipt(vertices, [0, 1, 2, 3, 4, 5])))
            table.write_text(json.dumps(sections()))
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--geometry", str(mesh),
                 "--sections", str(table), "--mesh", "body", "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("non-finite lateral section width", result.stderr)
            self.assertNotIn('"passed": true', result.stdout)
            self.assertNotIn("NaN", result.stdout)

    def test_normal_finite_triangles_keep_finite_widths(self):
        # A single continuous X/Z sheet backs the full lateral width; the
        # previous two isolated side walls were an invalid positive control.
        vertices = [
            [0, 0, -1], [2, 0, -1], [2, 0, 1], [0, 0, 1],
        ]
        result = taper.evaluate(
            receipt(vertices, [0, 1, 2, 0, 2, 3]), sections(), mesh_name="body"
        )
        self.assertTrue(result["passed"], result["failures"])
        self.assertTrue(all(math.isfinite(item["normalizedWidthError"])
                            for item in result["stations"]))
        self.assertTrue(all(math.isclose(item["lateralCoverageFraction"], 1.0)
                            for item in result["stations"]))


if __name__ == "__main__":
    unittest.main()
