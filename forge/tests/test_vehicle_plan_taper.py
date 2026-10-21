"""Synthetic positive/negative vehicle plan-view profile regressions, no browser needed."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "integrations" / "vehicle_form" / "plan_taper.py"
module_spec = importlib.util.spec_from_file_location("vehicle_plan_taper", SCRIPT)
assert module_spec and module_spec.loader
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)


def table(widths=(0.6, 1.0, 0.8, 1.0, 0.5)):
    return {
        "schemaVersion": 1,
        "axis": "x", "lateralAxis": "z",
        "reference": {"kind": "measured-top-view", "source": "synthetic plan-view image"},
        "maxNormalizedWidthError": 0.08,
        "maxTaperLoss": 0.12,
        "stations": [
            {"id": name, "x": float(x), "referenceWidth": float(width)}
            for x, name, width in zip((-2, -1, 0, 1, 2),
                                      ("nose", "front-fender", "door", "rear-hip", "tail"), widths)
        ],
    }


def car_mesh(widths=(0.6, 1.0, 0.8, 1.0, 0.5)):
    """Triangulated prism with actual width changes at vehicle X stations."""
    vertices = []
    for x, width in zip((-2, -1, 0, 1, 2), widths):
        for y, z in ((0, -width/2), (0, width/2), (1, width/2), (1, -width/2)):
            vertices.append([float(x), float(y), float(z)])
    tris = []
    for i in range(4):
        a, b = 4 * i, 4 * (i + 1)
        for k in range(4):
            c, d = (k + 1) % 4, k
            tris.extend((a + d, b + d, b + c, a + d, b + c, a + c))
    tris.extend((0, 2, 1, 0, 3, 2, 16, 17, 18, 16, 18, 19))
    return {"coordinateSpace": "world", "incomplete": False,
            "meshes": [{"name": "body", "vertices": vertices, "indices": tris}]}


class PlanTaperContract(unittest.TestCase):
    def test_matching_nose_fender_waist_and_tail_pass(self):
        report = module.evaluate(car_mesh(), table(), mesh_name="body")
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["measuredStationCount"], 5)
        self.assertGreater(report["triangleCount"], 20)
        self.assertTrue(all(row["intersectionCount"] >= 2 for row in report["stations"]))
        self.assertLess(max(row["normalizedWidthError"] for row in report["stations"]), 1e-12)

    def test_between_vertex_station_interpolates_triangle_intersections(self):
        # A nearest-vertex gate would measure 1.0 or 0.6; at x=-1.5 the
        # world-space triangle intersection is exactly halfway, width 0.8.
        sections = table()
        sections["stations"][1]["x"] = -1.5
        sections["stations"][1]["referenceWidth"] = 0.8
        report = module.evaluate(car_mesh(), sections, mesh_name="body")
        self.assertTrue(report["passed"], report["failures"])
        self.assertAlmostEqual(report["stations"][1]["measuredWidth"], 0.8)

    def test_side_only_rails_cannot_mimic_a_complete_body_width(self):
        # Keep only the two longitudinal side surfaces from an otherwise
        # exact reference-profile prism. Every station still has the correct
        # min/max Z, but no triangle supports the span between these rails.
        specimen = car_mesh()
        indices = specimen["meshes"][0]["indices"]
        side_only = []
        for strip in range(4):
            for side in (1, 3):
                start = strip * 24 + side * 6
                side_only.extend(indices[start:start + 6])
        specimen["meshes"][0]["indices"] = side_only
        self.assertEqual(len(side_only), 48)
        with self.assertRaisesRegex(module.PlanTaperInputError, "surface-backed lateral coverage"):
            module.evaluate(specimen, table(), mesh_name="body")

    def test_connected_surface_has_full_lateral_coverage_receipts(self):
        report = module.evaluate(car_mesh(), table(), mesh_name="body")
        self.assertTrue(report["passed"])
        self.assertEqual(
            [row["lateralCoverageFraction"] for row in report["stations"]],
            [1.0] * 5,
        )

    def test_constant_width_stadium_body_is_rejected(self):
        report = module.evaluate(car_mesh((1, 1, 1, 1, 1)), table(), mesh_name="body")
        self.assertFalse(report["passed"])
        self.assertTrue(any("taper collapsed" in error for error in report["failures"]))
        self.assertGreater(report["referenceTaper"], report["measuredTaper"])

    def test_hip_missing_is_rejected_even_if_other_sections_match(self):
        report = module.evaluate(car_mesh((0.6, 1.0, 0.8, 0.62, 0.5)), table(), mesh_name="body")
        self.assertFalse(report["passed"])
        self.assertTrue(any("rear-hip" in error for error in report["failures"]))

    def test_uniform_global_width_scale_does_not_fail_shape_gate(self):
        profile = (0.6, 1.0, 0.8, 1.0, 0.5)
        report = module.evaluate(car_mesh(tuple(v*2.5 for v in profile)), table(profile), mesh_name="body")
        self.assertTrue(report["passed"], report["failures"])

    def test_grouped_and_flat_triangle_indices_have_same_measurements(self):
        mesh = car_mesh()
        flat = module.evaluate(mesh, table(), mesh_name="body")
        indices = mesh["meshes"][0]["indices"]
        mesh["meshes"][0]["indices"] = [indices[i:i+3] for i in range(0, len(indices), 3)]
        grouped = module.evaluate(mesh, table(), mesh_name="body")
        self.assertEqual([row["measuredWidth"] for row in flat["stations"]],
                         [row["measuredWidth"] for row in grouped["stations"]])

    def test_collinear_edges_at_every_station_are_not_surface_evidence(self):
        # This fake car is only five isolated horizontal lines. The old
        # slice algorithm saw min/max Z at every X and returned a false pass.
        vertices, indices = [], []
        for x in (-2, -1, 0, 1, 2):
            base = len(vertices)
            vertices.extend([[x, 0, -1], [x, 0, 0], [x, 0, 1]])
            indices.extend([base, base + 1, base + 2])
        mesh = {"coordinateSpace": "world", "incomplete": False, "meshes": [
            {"name": "body", "vertices": vertices, "indices": indices}
        ]}
        with self.assertRaisesRegex(module.PlanTaperInputError, "no nondegenerate surface"):
            module.evaluate(mesh, table((1, 1, 1, 1, 1)), mesh_name="body")

    def test_degenerate_wide_spike_does_not_poison_valid_plan_profile(self):
        mesh = car_mesh()
        part = mesh["meshes"][0]
        base = len(part["vertices"])
        part["vertices"].extend([[0, 0, -100], [0, 0, 0], [0, 0, 100]])
        part["indices"].extend([base, base + 1, base + 2])
        report = module.evaluate(mesh, table(), mesh_name="body")
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["degenerateTrianglesIgnored"], 1)
        self.assertAlmostEqual(report["stations"][2]["measuredWidth"], 0.8)

    def test_repeated_vertex_face_is_ignored_without_corrupting_measured_body(self):
        mesh = car_mesh()
        mesh["meshes"][0]["indices"].extend([0, 0, 1])
        report = module.evaluate(mesh, table(), mesh_name="body")
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["degenerateTrianglesIgnored"], 1)

    def test_missing_center_slice_has_no_false_pass(self):
        mesh = car_mesh()
        spec = table()
        spec["stations"][2]["x"] = 20.0
        # Deliberately no longer sorted; still a malformed input, not a profile verdict.
        with self.assertRaisesRegex(module.PlanTaperInputError, "strictly increasing"):
            module.evaluate(mesh, spec, mesh_name="body")
        spec["stations"][-1]["x"] = 21.0
        spec["stations"][-2]["x"] = 20.5
        with self.assertRaisesRegex(module.PlanTaperInputError, "no measurable"):
            module.evaluate(mesh, spec, mesh_name="body")

    def test_missing_or_duplicated_body_is_error(self):
        mesh = car_mesh()
        with self.assertRaisesRegex(module.PlanTaperInputError, "found 0"):
            module.evaluate(mesh, table(), mesh_name="greenhouse")
        mesh["meshes"].append(dict(mesh["meshes"][0]))
        with self.assertRaisesRegex(module.PlanTaperInputError, "found 2"):
            module.evaluate(mesh, table(), mesh_name="body")

    def test_partial_and_local_space_evidence_refused(self):
        mesh = car_mesh()
        mesh["incomplete"] = True
        with self.assertRaisesRegex(module.PlanTaperInputError, "partial"):
            module.evaluate(mesh, table(), mesh_name="body")
        mesh["incomplete"] = False
        mesh["coordinateSpace"] = "local"
        with self.assertRaisesRegex(module.PlanTaperInputError, "world"):
            module.evaluate(mesh, table(), mesh_name="body")

    def test_partial_receipt_requires_explicit_boolean_false(self):
        # An exporter that skipped unsupported geometry cannot be certified
        # merely because its incomplete field was serialized incorrectly.
        for value in (True, None, 0, 1, "", "false", "true", [], {}):
            with self.subTest(incomplete=value):
                receipt = car_mesh()
                receipt["incomplete"] = value
                with self.assertRaisesRegex(module.PlanTaperInputError, "partial or unverified"):
                    module.evaluate(receipt, table(), mesh_name="body")
        receipt = car_mesh()
        del receipt["incomplete"]
        with self.assertRaisesRegex(module.PlanTaperInputError, "partial or unverified"):
            module.evaluate(receipt, table(), mesh_name="body")
        self.assertTrue(module.evaluate(car_mesh(), table(), mesh_name="body")["passed"])

    def test_active_skips_cannot_hide_omitted_vehicle_body_geometry(self):
        for field in ("skipped", "skippedMeshes"):
            for reason in ("vertex-budget", "skinned", "unsupported", None):
                with self.subTest(field=field, reason=reason):
                    receipt = car_mesh()
                    receipt[field] = [{"name": "unmeasured-panel", "reason": reason}]
                    with self.assertRaisesRegex(module.PlanTaperInputError, "omits active"):
                        module.evaluate(receipt, table(), mesh_name="body")

    def test_hidden_skips_are_allowed_but_malformed_skip_lists_fail(self):
        receipt = car_mesh()
        receipt["skippedMeshes"] = [
            {"name": "studio-ground", "reason": "hidden"},
            {"name": "debug-overlay", "reason": "filtered"},
        ]
        self.assertTrue(module.evaluate(receipt, table(), mesh_name="body")["passed"])
        for bad in (None, {}, "hidden", [{"reason": "unknown"}], ["hidden"]):
            with self.subTest(bad=bad):
                receipt = car_mesh()
                receipt["skipped"] = bad
                with self.assertRaises(module.PlanTaperInputError):
                    module.evaluate(receipt, table(), mesh_name="body")

    def test_missing_top_view_reference_is_refused(self):
        spec = table()
        spec["reference"]["source"] = ""
        with self.assertRaisesRegex(module.PlanTaperInputError, "source"):
            module.evaluate(car_mesh(), spec, mesh_name="body")

    def test_invalid_station_value_and_bad_indices_refused(self):
        spec = table()
        spec["stations"][1]["referenceWidth"] = float("nan")
        with self.assertRaisesRegex(module.PlanTaperInputError, "finite"):
            module.evaluate(car_mesh(), spec, mesh_name="body")
        mesh = car_mesh()
        mesh["meshes"][0]["indices"][3] = len(mesh["meshes"][0]["vertices"]) + 99
        with self.assertRaisesRegex(module.PlanTaperInputError, "invalid vertex index"):
            module.evaluate(mesh, table(), mesh_name="body")

    def test_rail_only_cli_fails_closed_without_fabricated_profile(self):
        specimen = car_mesh()
        indices = specimen["meshes"][0]["indices"]
        specimen["meshes"][0]["indices"] = [
            value
            for strip in range(4)
            for side in (1, 3)
            for value in indices[strip * 24 + side * 6:strip * 24 + side * 6 + 6]
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            geo, sections = root / "mesh.json", root / "sections.json"
            geo.write_text(json.dumps(specimen), encoding="utf-8")
            sections.write_text(json.dumps(table()), encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(SCRIPT), "--geometry", str(geo),
                "--sections", str(sections), "--mesh", "body", "--json",
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("surface-backed lateral coverage", result.stderr)
            self.assertNotIn('"passed": true', result.stdout)

    def test_cli_pass_fail_and_error_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            geometry = root / "geometry.json"
            sections = root / "sections.json"
            geometry.write_text(json.dumps(car_mesh()), encoding="utf-8")
            sections.write_text(json.dumps(table()), encoding="utf-8")
            args = [sys.executable, str(SCRIPT), "--geometry", str(geometry), "--sections", str(sections), "--mesh", "body", "--json"]
            ok = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertTrue(json.loads(ok.stdout)["passed"])
            geometry.write_text(json.dumps(car_mesh((1, 1, 1, 1, 1))), encoding="utf-8")
            bad = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(bad.returncode, 1, bad.stderr)
            self.assertFalse(json.loads(bad.stdout)["passed"])
            # Keep a valid completeness receipt so this case specifically
            # exercises coordinate-space rejection rather than the earlier
            # fail-closed completeness gate.
            geometry.write_text(json.dumps({"coordinateSpace": "local", "incomplete": False}), encoding="utf-8")
            invalid = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("coordinateSpace", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
