"""Binary STL coordinates must survive float32 quantization without collapsed faces."""
from __future__ import annotations

import contextlib
import io
import json
import math
import struct
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

    def test_thin_closed_tetrahedron_fails_when_float32_erases_volume(self):
        # STL quantization at z=1000 rounds a 1e-5-high apex to the base
        # plane. The apex remains a distinct (x,y) point, and all four
        # triangles still have positive 2D area, so a face-only gate misses it.
        thin = {
            "name": "thin-tetra",
            "vertices": [
                [0, 0, 1000], [1, 0, 1000], [0, 1, 1000],
                [0.2, 0.2, 1000.00001],
            ],
            "indices": FACES,
        }
        result = print_export.build_export([thin])
        self.assertTrue(result["report"]["watertight"])
        self.assertEqual(result["report"]["zeroVolumeShellCount"], 0)
        self.assertGreater(result["report"]["volume"], 0)
        with tempfile.TemporaryDirectory() as directory:
            stl = Path(directory) / "flat-after-rounding.stl"
            with self.assertRaisesRegex(print_export.PrintExportError,
                                        "loses its enclosed volume at STL float32 precision"):
                print_export.write_stl(stl, result["vertices"], result["triangles"])
            self.assertFalse(stl.exists())
            obj = Path(directory) / "original-height.obj"
            print_export.write_obj(obj, result["vertices"], result["triangles"])
            self.assertIn("1000.00001", obj.read_text())

    def test_apex_height_above_float32_ulp_can_still_export(self):
        taller = {
            "name": "tetra",
            "vertices": [
                [0, 0, 1000], [1, 0, 1000], [0, 1, 1000],
                [0.2, 0.2, 1000.001],
            ],
            "indices": FACES,
        }
        result = print_export.build_export([taller])
        self.assertTrue(result["report"]["watertight"])
        with tempfile.TemporaryDirectory() as directory:
            stl = Path(directory) / "surviving-height.stl"
            print_export.write_stl(stl, result["vertices"], result["triangles"])
            self.assertEqual(stl.stat().st_size, 84 + 4 * 50)

    def test_stl_rejects_face_winding_reversal_after_float32_rounding(self):
        # These three source points form a clockwise, nonzero-area triangle.
        # All rounded points remain distinct with nonzero area, but at x/y
        # near 1000 the stored float32 triangle becomes counterclockwise.
        vertices = [
            (1000.00010798837, 999.9999936490749, 0.0),
            (999.999942614087, 999.9999363445476, 0.0),
            (999.9998271900251, 999.999898148074, 0.0),
        ]
        def signed_area_xy(points):
            a, b, c = points
            return ((b[0] - a[0]) * (c[1] - a[1]) -
                    (b[1] - a[1]) * (c[0] - a[0]))
        quantized = [
            tuple(struct.unpack("<f", struct.pack("<f", x))[0] for x in vertex)
            for vertex in vertices
        ]
        self.assertLess(signed_area_xy(vertices), 0)
        self.assertGreater(signed_area_xy(quantized), 0)
        with tempfile.TemporaryDirectory() as directory:
            stl = Path(directory) / "reversed.stl"
            with self.assertRaisesRegex(print_export.PrintExportError, "reverses winding"):
                print_export.write_stl(stl, vertices, [(0, 1, 2)])
            self.assertFalse(stl.exists())

    def test_serialized_facet_normal_matches_rounded_stl_vertices(self):
        # Quantization changes this triangle's slope appreciably without
        # destroying its orientation. The STL normal must match the *stored*
        # vertices, not the more precise authored triangle.
        vertices = [
            (1000.0, 1000.0, 1000.0),
            (1000.00013, 1000.0, 1000.0),
            (1000.00001, 1000.00013, 1000.00008),
        ]
        with tempfile.TemporaryDirectory() as directory:
            stl = Path(directory) / "rounded-normal.stl"
            print_export.write_stl(stl, vertices, [(0, 1, 2)])
            payload = stl.read_bytes()
            self.assertEqual(len(payload), 84 + 50)
            self.assertEqual(struct.unpack_from("<I", payload, 80)[0], 1)
            facet = struct.unpack_from("<12f", payload, 84)
        written_normal = facet[:3]
        a, b, c = [facet[i:i + 3] for i in (3, 6, 9)]
        u = tuple(b[i] - a[i] for i in range(3))
        v = tuple(c[i] - a[i] for i in range(3))
        cross = (u[1] * v[2] - u[2] * v[1],
                 u[2] * v[0] - u[0] * v[2],
                 u[0] * v[1] - u[1] * v[0])
        expected = tuple(x / math.hypot(*cross) for x in cross)
        for component, measured in zip(expected, written_normal):
            self.assertAlmostEqual(component, measured, places=6)
        self.assertAlmostEqual(math.hypot(*written_normal), 1.0, places=6)

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
