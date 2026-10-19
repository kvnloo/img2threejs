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
