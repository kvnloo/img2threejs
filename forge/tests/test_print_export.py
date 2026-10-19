#!/usr/bin/env python3
"""Tests for the printable STL/OBJ exporter (issue #3).

The load-bearing tests are the refusals: an open box, a non-manifold fin, and a box with one face
wound backwards must each be reported and NOT written without --allow-open. An exporter that emits a
broken STL silently is worse than none, because the slicer failure surfaces hours later.

Pure Python 3.10+ stdlib.
"""

from __future__ import annotations

import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stage3_build"))

import print_export  # noqa: E402

CUBE_VERTICES = [
    [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
    [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
]
# Outward-facing, counter-clockwise when viewed from outside.
CUBE_FACES = [
    [0, 2, 1], [0, 3, 2],  # -Z
    [4, 5, 6], [4, 6, 7],  # +Z
    [0, 1, 5], [0, 5, 4],  # -Y
    [3, 7, 6], [3, 6, 2],  # +Y
    [0, 4, 7], [0, 7, 3],  # -X
    [1, 2, 6], [1, 6, 5],  # +X
]


def cube(offset=(0.0, 0.0, 0.0), size=1.0, name="cube", faces=None):
    return {
        "name": name,
        "vertices": [[offset[i] + size * v[i] for i in range(3)] for v in CUBE_VERTICES],
        "indices": [list(face) for face in (faces or CUBE_FACES)],
    }


def unindexed_cube():
    soup = []
    for face in CUBE_FACES:
        soup.extend(CUBE_VERTICES[i] for i in face)
    return {"name": "soup", "vertices": soup}


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = print_export.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


class ClosedSolids(unittest.TestCase):
    def test_cube_is_watertight_with_positive_unit_volume(self):
        report = print_export.build_export([cube()])["report"]
        self.assertTrue(report["watertight"])
        self.assertEqual(report["shellCount"], 1)
        self.assertEqual(report["insideOutShellCount"], 0)
        self.assertAlmostEqual(report["volume"], 1.0, places=9)
        self.assertEqual(report["triangleCount"], 12)
        self.assertEqual(report["vertexCount"], 8)

    def test_unindexed_soup_is_welded_into_a_closed_shell(self):
        report = print_export.build_export([unindexed_cube()])["report"]
        self.assertTrue(report["watertight"])
        self.assertEqual(report["vertexCount"], 8)

    def test_weld_tolerance_closes_float_noise_seams(self):
        noisy = unindexed_cube()
        noisy["vertices"] = [[c + (1e-9 if n % 2 else -1e-9) for c in v] for n, v in enumerate(noisy["vertices"])]
        self.assertTrue(print_export.build_export([noisy])["report"]["watertight"])

    def test_two_disjoint_parts_are_two_closed_shells(self):
        report = print_export.build_export([cube(), cube(offset=(3, 0, 0), name="b")])["report"]
        self.assertTrue(report["watertight"])
        self.assertEqual(report["shellCount"], 2)
        self.assertAlmostEqual(report["volume"], 2.0, places=9)

    def test_scale_to_longest_edge_in_mm(self):
        result = print_export.build_export([cube(size=0.25)], longest_edge_mm=80)
        report = result["report"]
        self.assertAlmostEqual(report["scaleFactor"], 320.0)
        self.assertEqual(report["units"], "mm")
        self.assertAlmostEqual(max(report["bounds"]["size"]), 80.0, places=6)
        self.assertAlmostEqual(report["volume"], 80.0 ** 3, places=3)


class BrokenSolidsAreReported(unittest.TestCase):
    def test_open_box_reports_boundary_edges(self):
        report = print_export.build_export([cube(faces=CUBE_FACES[2:])])["report"]
        self.assertFalse(report["watertight"])
        self.assertEqual(report["boundaryEdgeCount"], 4)
        self.assertFalse(report["shells"][0]["closed"])

    def test_fin_sharing_an_edge_is_non_manifold(self):
        mesh = cube()
        mesh["vertices"].append([0.5, -1, 0])
        mesh["indices"].append([0, 1, 8])
        report = print_export.build_export([mesh])["report"]
        self.assertFalse(report["watertight"])
        self.assertEqual(report["nonManifoldEdgeCount"], 1)

    def test_one_backwards_face_is_misoriented(self):
        faces = [list(face) for face in CUBE_FACES]
        faces[0] = [faces[0][0], faces[0][2], faces[0][1]]
        report = print_export.build_export([cube(faces=faces)])["report"]
        self.assertFalse(report["watertight"])
        self.assertGreater(report["misorientedEdgeCount"], 0)

    def test_fully_flipped_cube_is_inside_out(self):
        faces = [[a, c, b] for a, b, c in CUBE_FACES]
        report = print_export.build_export([cube(faces=faces)])["report"]
        self.assertTrue(report["watertight"])
        self.assertEqual(report["insideOutShellCount"], 1)
        self.assertLess(report["volume"], 0)

    def test_degenerate_triangles_are_dropped_and_counted(self):
        mesh = cube()
        mesh["indices"].append([0, 0, 1])
        mesh["vertices"].append([2, 0, 0])
        mesh["indices"].append([0, 1, 8])  # collinear: zero area
        report = print_export.build_export([mesh])["report"]
        self.assertEqual(report["degenerateTrianglesDropped"], 2)
        self.assertTrue(report["watertight"])
        self.assertEqual(report["vertexCount"], 8)


class InputValidation(unittest.TestCase):
    def assertRejects(self, meshes, fragment):
        with self.assertRaises(print_export.PrintExportError) as caught:
            print_export.build_export(meshes)
        self.assertIn(fragment, str(caught.exception))

    def test_empty_inputs_fail_closed(self):
        self.assertRejects([], "no meshes")
        self.assertRejects([{"name": "x", "vertices": []}], "no vertices")

    def test_bad_indices(self):
        self.assertRejects([{"vertices": CUBE_VERTICES, "indices": [0, 1, 99]}], "out of range")
        self.assertRejects([{"vertices": CUBE_VERTICES, "indices": [0, 1]}], "multiple of 3")
        self.assertRejects([{"vertices": CUBE_VERTICES, "indices": [0, 1, True]}], "out of range")

    def test_non_finite_vertex(self):
        self.assertRejects([{"vertices": [[0, 0, float("nan")], [1, 0, 0], [0, 1, 0]]}], "non-finite")

    def test_load_meshes_shapes(self):
        self.assertEqual(len(print_export.load_meshes({"meshes": [cube()]})), 1)
        self.assertEqual(len(print_export.load_meshes(cube())), 1)
        with self.assertRaises(print_export.PrintExportError):
            print_export.load_meshes({"nothing": 1})


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, payload):
        path = self.tmp / "meshes.json"
        path.write_text(json.dumps(payload))
        return path

    def test_stl_binary_layout_and_report(self):
        src = self.write({"meshes": [cube()]})
        out, rep = self.tmp / "model.stl", self.tmp / "report.json"
        code, stdout, _ = run_cli(src, "--out", out, "--longest-edge-mm", 50, "--report", rep)
        self.assertEqual(code, 0, stdout)
        data = out.read_bytes()
        (count,) = struct.unpack_from("<I", data, 80)
        self.assertEqual(count, 12)
        self.assertEqual(len(data), 84 + 50 * count)
        floats = [struct.unpack_from("<12f", data, 84 + 50 * n) for n in range(count)]
        coords = [c for tri in floats for c in tri[3:]]
        self.assertAlmostEqual(max(coords), 50.0, places=4)
        # Facet normals point outward: for each triangle, normal . (centroid - cube centre) > 0.
        for tri in floats:
            normal = tri[:3]
            centroid = [(tri[3 + i] + tri[6 + i] + tri[9 + i]) / 3 - 25.0 for i in range(3)]
            self.assertGreater(sum(n * c for n, c in zip(normal, centroid)), 0)
        report = json.loads(rep.read_text())
        self.assertTrue(report["printable"])
        self.assertTrue(report["written"])

    def test_obj_output(self):
        src = self.write([cube()])
        out = self.tmp / "model.obj"
        code, _, _ = run_cli(src, "--out", out)
        self.assertEqual(code, 0)
        lines = out.read_text().splitlines()
        self.assertEqual(sum(line.startswith("v ") for line in lines), 8)
        self.assertEqual(sum(line.startswith("f ") for line in lines), 12)
        self.assertIn("f 1 3 2", lines)

    def test_open_mesh_is_refused_without_allow_open(self):
        src = self.write([cube(faces=CUBE_FACES[2:])])
        out = self.tmp / "open.stl"
        code, stdout, _ = run_cli(src, "--out", out, "--json")
        self.assertEqual(code, 1)
        self.assertFalse(out.exists())
        report = json.loads(stdout)
        self.assertFalse(report["written"])
        self.assertIsNone(report["output"])
        code, _, _ = run_cli(src, "--out", out, "--allow-open")
        self.assertEqual(code, 1)
        self.assertTrue(out.exists())

    def test_inside_out_mesh_is_refused(self):
        src = self.write([cube(faces=[[a, c, b] for a, b, c in CUBE_FACES])])
        out = self.tmp / "flipped.stl"
        code, _, _ = run_cli(src, "--out", out)
        self.assertEqual(code, 1)
        self.assertFalse(out.exists())

    def test_input_errors_exit_2(self):
        src = self.write({"meshes": [{"name": "empty", "vertices": []}]})
        code, _, err = run_cli(src, "--out", self.tmp / "x.stl")
        self.assertEqual(code, 2)
        self.assertIn("no vertices", err)

    def test_existing_output_needs_force(self):
        src = self.write([cube()])
        out = self.tmp / "model.stl"
        out.write_bytes(b"keep")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            print_export.main([str(src), "--out", str(out)])
        self.assertEqual(out.read_bytes(), b"keep")
        code, _, _ = run_cli(src, "--out", out, "--force")
        self.assertEqual(code, 0)

    def test_unknown_suffix_requires_format(self):
        src = self.write([cube()])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            print_export.main([str(src), "--out", str(self.tmp / "model.bin")])
        code, _, _ = run_cli(src, "--out", self.tmp / "model.bin", "--format", "stl")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
