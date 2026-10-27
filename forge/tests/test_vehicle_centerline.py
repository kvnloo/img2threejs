"""Optional measured vehicle centerline alignment on real world-space triangle sections.

All fixtures are synthetic. These tests do not claim photographic reconstruction.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from forge.tests.test_vehicle_plan_taper import SCRIPT, car_mesh, module, table


def table_with_centers(*, tolerance=0.08, centers=(0, 0, 0, 0, 0)):
    reference = table()
    reference["maxNormalizedCenterError"] = tolerance
    for row, center in zip(reference["stations"], centers):
        row["referenceCenterZ"] = center
    return reference


def translated_body(shift, *, station_x=None):
    specimen = car_mesh()
    for vertex in specimen["meshes"][0]["vertices"]:
        if station_x is None or vertex[0] == station_x:
            vertex[2] += shift
    return specimen


class VehicleCenterlineEvidenceTest(unittest.TestCase):
    def test_aligned_reference_tracks_a_center_at_each_station(self):
        report = module.evaluate(car_mesh(), table_with_centers(), mesh_name="body")
        self.assertTrue(report["passed"], report["failures"])
        self.assertTrue(report["centerlineCompared"])
        self.assertEqual(report["maxNormalizedCenterError"], 0.08)
        self.assertTrue(all(abs(row["measuredCenterZ"]) < 1e-12 for row in report["stations"]))
        self.assertTrue(all(row["normalizedCenterError"] < 1e-12 for row in report["stations"]))

    def test_lateral_translation_is_invisible_to_width_only_gate_but_fails_center(self):
        displaced = translated_body(0.3)
        legacy = module.evaluate(displaced, table(), mesh_name="body")
        self.assertTrue(legacy["passed"], legacy["failures"])
        self.assertFalse(legacy["centerlineCompared"])
        self.assertNotIn("normalizedCenterError", legacy["stations"][0])
        aligned = module.evaluate(displaced, table_with_centers(), mesh_name="body")
        self.assertFalse(aligned["passed"])
        self.assertTrue(all(row["normalizedWidthError"] < 1e-12 for row in aligned["stations"]))
        self.assertEqual(len(aligned["failures"]), 5)
        self.assertTrue(all("center error" in msg for msg in aligned["failures"]))
        self.assertAlmostEqual(aligned["stations"][0]["measuredCenterZ"], 0.3)

    def test_one_station_centerline_kink_is_detected(self):
        specimen = translated_body(0.22, station_x=0.0)
        report = module.evaluate(specimen, table_with_centers(), mesh_name="body")
        self.assertFalse(report["passed"])
        self.assertTrue(any("door" in msg and "center error" in msg for msg in report["failures"]))
        self.assertTrue(all(row["normalizedWidthError"] < 1e-12 for row in report["stations"]))

    def test_near_centered_body_passes_declared_tolerance(self):
        report = module.evaluate(translated_body(0.03), table_with_centers(), mesh_name="body")
        self.assertTrue(report["passed"], report["failures"])
        self.assertAlmostEqual(report["stations"][0]["normalizedCenterError"], 0.03)

    def test_width_scaling_still_matches_shape_when_centered(self):
        widths = (0.6, 1.0, 0.8, 1.0, 0.5)
        scaled = tuple(width * 2.5 for width in widths)
        specimen = car_mesh(scaled)
        result = module.evaluate(specimen, table_with_centers(), mesh_name="body")
        self.assertTrue(result["passed"], result["failures"])

    def test_partial_or_unmeasured_centerline_is_not_silently_skipped(self):
        partial = table_with_centers()
        del partial["stations"][2]["referenceCenterZ"]
        with self.assertRaisesRegex(module.PlanTaperInputError, "at every station"):
            module.evaluate(car_mesh(), partial, mesh_name="body")
        no_centers = table()
        no_centers["maxNormalizedCenterError"] = 0.10
        with self.assertRaisesRegex(module.PlanTaperInputError, "requires referenceCenterZ"):
            module.evaluate(car_mesh(), no_centers, mesh_name="body")

    def test_bad_center_values_and_tolerances_are_rejected(self):
        for bad in (True, None, "0", float("nan"), float("inf"), 10 ** 500):
            with self.subTest(center=repr(bad)):
                specs = table_with_centers()
                specs["stations"][1]["referenceCenterZ"] = bad
                with self.assertRaisesRegex(module.PlanTaperInputError, "referenceCenterZ"):
                    module.evaluate(car_mesh(), specs, mesh_name="body")
        for bad in (-1, 1, float("nan"), "0.1", True):
            with self.subTest(tolerance=bad):
                specs = table_with_centers(tolerance=bad)
                with self.assertRaises(module.PlanTaperInputError):
                    module.evaluate(car_mesh(), specs, mesh_name="body")

    def test_normalized_center_error_must_be_finite(self):
        reference = table_with_centers()
        for row in reference["stations"]:
            row["referenceWidth"] = 1e-308
            row["referenceCenterZ"] = -1e308
        with self.assertRaisesRegex(module.PlanTaperInputError, "non-finite normalized lateral center"):
            module.evaluate(car_mesh(), reference, mesh_name="body")

    def test_cli_reports_centerline_mismatch_with_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            meshes, sections = root / "body.json", root / "measured.json"
            meshes.write_text(json.dumps(translated_body(0.3)), encoding="utf-8")
            sections.write_text(json.dumps(table_with_centers()), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--geometry", str(meshes),
                 "--sections", str(sections), "--mesh", "body", "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertTrue(receipt["centerlineCompared"])
            self.assertFalse(receipt["passed"])
            self.assertTrue(any("center error" in msg for msg in receipt["failures"]))


if __name__ == "__main__":
    unittest.main()
