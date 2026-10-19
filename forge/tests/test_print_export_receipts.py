"""Fail closed on incomplete or untransformed browser mesh-export receipts."""
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


MESH = {
    "name": "tetra",
    "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
    "indices": [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
}


class MeshReceiptGateTest(unittest.TestCase):
    def test_complete_world_space_receipt_can_export(self):
        receipt = {"coordinateSpace": "world", "incomplete": False, "meshes": [MESH]}
        meshes = print_export.load_meshes(receipt)
        self.assertEqual(meshes, [MESH])
        self.assertTrue(print_export.build_export(meshes)["report"]["watertight"])

    def test_partial_receipt_cannot_be_called_printable(self):
        for flag in (True, None, "false", 0):
            with self.subTest(incomplete=flag):
                receipt = {"meshes": [MESH], "incomplete": flag}
                with self.assertRaisesRegex(print_export.PrintExportError, "incomplete"):
                    print_export.load_meshes(receipt)

    def test_declared_local_space_is_rejected(self):
        for coordinate_space in ("local", "camera", "screen"):
            with self.subTest(coordinateSpace=coordinate_space):
                with self.assertRaisesRegex(print_export.PrintExportError, "world-space"):
                    print_export.load_meshes({
                        "coordinateSpace": coordinate_space, "meshes": [MESH],
                    })

    def test_legacy_mesh_input_is_still_supported(self):
        self.assertEqual(print_export.load_meshes(MESH), [MESH])
        self.assertEqual(print_export.load_meshes([MESH]), [MESH])
        self.assertEqual(print_export.load_meshes({"meshes": [MESH]}), [MESH])

    def test_allow_open_cannot_override_incomplete_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            receipt = directory / "meshes.json"
            output = directory / "model.stl"
            receipt.write_text(json.dumps({
                "coordinateSpace": "world", "incomplete": True,
                "skippedMeshes": [{"name": "visible-arm", "reason": "skinned"}],
                "meshes": [MESH],
            }), encoding="utf-8")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                code = print_export.main(
                    [str(receipt), "--out", str(output), "--allow-open"]
                )
            self.assertEqual(code, 2, errors.getvalue())
            self.assertIn("incomplete", errors.getvalue())
            self.assertFalse(output.exists())

    def test_force_does_not_replace_existing_output_with_incomplete_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            receipt = directory / "meshes.json"
            output = directory / "model.stl"
            sentinel = b"existing complete printable file"
            output.write_bytes(sentinel)
            receipt.write_text(json.dumps({
                "coordinateSpace": "world", "incomplete": True, "meshes": [MESH],
            }), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                code = print_export.main(
                    [str(receipt), "--out", str(output), "--force"]
                )
            self.assertEqual(code, 2)
            self.assertEqual(output.read_bytes(), sentinel)


if __name__ == "__main__":
    unittest.main()
