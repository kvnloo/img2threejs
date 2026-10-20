"""Binary STL coordinates must survive float32 quantization without collapsed faces."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage3_build"))
import print_export  # noqa: E402


FACES = [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]
CUBE_FACES = [
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
    [0, 1, 5], [0, 5, 4], [3, 7, 6], [3, 6, 2],
    [0, 4, 7], [0, 7, 3], [1, 2, 6], [1, 6, 5],
]


def closed_box(x):
    return {
        "name": "separate-solid",
        "vertices": [[x + a, b, c] for a, b, c in (
            (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
            (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
        )],
        "indices": CUBE_FACES,
    }


def tetra(scale=1.0, shift=0.0):
    return {
        "name": "tetra",
        "vertices": [
            [shift, 0, 0],
            [shift + scale, 0, 0],
            [shift, scale, 0],
            [shift, 0, scale],
        ],
        "indices": FACES,
    }


class Float32GeometryGateTest(unittest.TestCase):
    def test_small_geometry_requires_scaling_for_binary_stl(self):
        model = print_export.build_export([tetra(1e-50)], weld=1e-60)
        self.assertTrue(model["report"]["watertight"])
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "tiny.stl"
            with self.assertRaisesRegex(print_export.PrintExportError, "float32 precision"):
                print_export.write_stl(out, model["vertices"], model["triangles"])
            self.assertFalse(out.exists())

    def test_large_world_offset_must_not_flatten_a_face(self):
        model = print_export.build_export([tetra(1.0, shift=1e10)])
        self.assertTrue(model["report"]["watertight"])
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "offset.stl"
            with self.assertRaisesRegex(print_export.PrintExportError, "float32 precision"):
                print_export.write_stl(out, model["vertices"], model["triangles"])
            self.assertFalse(out.exists())

    def test_float32_rounded_gap_cannot_merge_two_closed_solids(self):
        # Each cube is a watertight unit solid. A real 1e-5 source-space gap
        # exceeds the source weld tolerance, but the float32 ULP at x=1001
        # is ~6.1e-5, so both facing surfaces would serialize at x=1001.
        source = [closed_box(1000.0), closed_box(1001.00001)]
        result = print_export.build_export(source)
        self.assertTrue(result["report"]["watertight"])
        self.assertEqual(result["report"]["shellCount"], 2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stl = root / "false-touch.stl"
            with self.assertRaisesRegex(print_export.PrintExportError, "collide at STL float32 precision"):
                print_export.write_stl(stl, result["vertices"], result["triangles"])
            self.assertFalse(stl.exists())
            # OBJ serializes the original double precision positions;
            # don't block it merely because the STL format cannot represent them.
            obj = root / "original-precision.obj"
            print_export.write_obj(obj, result["vertices"], result["triangles"])
            self.assertEqual(sum(line.startswith("f ") for line in obj.read_text().splitlines()), 24)

    def test_force_cannot_overwrite_verified_stl_when_gap_disappears(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "two-boxes.json"
            stl = root / "trusted.stl"
            report = root / "report.json"
            source.write_text(json.dumps({"meshes": [
                closed_box(1000.0), closed_box(1001.00001),
            ]}), encoding="utf-8")
            sentinel = b"previous good print"
            stl.write_bytes(sentinel)
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                status = print_export.main([
                    str(source), "--out", str(stl), "--force",
                    "--allow-open", "--report", str(report),
                ])
            self.assertEqual(status, 2, errors.getvalue())
            self.assertIn("collide at STL float32 precision", errors.getvalue())
            self.assertEqual(stl.read_bytes(), sentinel)
            self.assertFalse(report.exists())
            self.assertFalse(list(root.glob(".*.tmp")))

    def test_wide_enough_gap_keeps_disjoint_watertight_shells(self):
        # The same two solids need not be rejected when their distinct
        # source coordinates remain distinct after float32 quantization.
        result = print_export.build_export([
            closed_box(1000.0), closed_box(1001.0002),
        ])
        self.assertEqual(result["report"]["shellCount"], 2)
        with tempfile.TemporaryDirectory() as directory:
            stl = Path(directory) / "two-solids.stl"
            print_export.write_stl(stl, result["vertices"], result["triangles"])
            self.assertEqual(stl.stat().st_size, 84 + 50 * 24)

    def test_normal_unit_tetrahedron_still_serializes(self):
        model = print_export.build_export([tetra()])
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "good.stl"
            print_export.write_stl(out, model["vertices"], model["triangles"])
            self.assertEqual(out.stat().st_size, 84 + 50 * len(FACES))

    def test_cli_rejects_quantization_collapse_without_overwriting_old_file(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "mesh.json"
            out = folder / "old.stl"
            source.write_text(json.dumps({"meshes": [tetra(1e-50)]}), encoding="utf-8")
            out.write_bytes(b"trusted prior export")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                code = print_export.main([
                    str(source), "--out", str(out), "--weld", "1e-60", "--force",
                ])
            self.assertEqual(code, 2, errors.getvalue())
            self.assertIn("float32 precision", errors.getvalue())
            self.assertEqual(out.read_bytes(), b"trusted prior export")


if __name__ == "__main__":
    unittest.main()
