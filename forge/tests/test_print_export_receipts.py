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

    def test_reported_active_skips_override_a_false_complete_claim(self):
        for field in ("skippedMeshes", "skipped"):
            for reason in ("skinned-mesh", "vertex-budget", None):
                with self.subTest(field=field, reason=reason):
                    data = {"meshes": [MESH], "coordinateSpace": "world",
                            "incomplete": False,
                            field: [{"name": "unexported-part", "reason": reason}]}
                    with self.assertRaisesRegex(print_export.PrintExportError, "omits active"):
                        print_export.load_meshes(data)

    def test_intentional_hidden_and_filtered_skips_do_not_block(self):
        data = {"meshes": [MESH], "coordinateSpace": "world", "incomplete": False,
                "skippedMeshes": [
                    {"name": "hidden-helper", "reason": "hidden"},
                    {"name": "filtered-part", "reason": "filtered"}]}
        self.assertEqual(print_export.load_meshes(data), [MESH])

    def test_malformed_skip_lists_fail_closed(self):
        for bad in (None, "hidden", {"reason": "hidden"}, ["hidden"], [{}]):
            with self.subTest(bad=bad):
                with self.assertRaises(print_export.PrintExportError):
                    print_export.load_meshes({
                        "meshes": [MESH], "incomplete": False, "skippedMeshes": bad})

    def test_legacy_mesh_input_is_still_supported(self):
        self.assertEqual(print_export.load_meshes(MESH), [MESH])
        self.assertEqual(print_export.load_meshes([MESH]), [MESH])
        self.assertEqual(print_export.load_meshes({"meshes": [MESH]}), [MESH])

    def test_exporter_markers_require_explicit_false_completeness(self):
        for fragment in (
            {"schemaVersion": 1, "coordinateSpace": "world"},
            {"coordinateSpace": "world"},
            {"skippedMeshes": []},
            {"skipped": [{"name": "invisible-floor", "reason": "filtered"}]},
        ):
            with self.subTest(fragment=fragment):
                receipt = {"meshes": [MESH], **fragment}
                with self.assertRaisesRegex(print_export.PrintExportError, "incomplete"):
                    print_export.load_meshes(receipt)
        # Historical mesh-only JSON remains a valid raw input, not a browser receipt.
        self.assertEqual(print_export.load_meshes({"meshes": [MESH]}), [MESH])

    def test_unknown_exporter_schema_version_is_not_certified(self):
        for invalid in (0, 2, "1", 1.0, True, None):
            with self.subTest(schemaVersion=invalid):
                receipt = {"meshes": [MESH], "schemaVersion": invalid,
                           "coordinateSpace": "world", "incomplete": False}
                with self.assertRaisesRegex(print_export.PrintExportError, "schemaVersion"):
                    print_export.load_meshes(receipt)
        self.assertEqual(print_export.load_meshes({
            "schemaVersion": 1, "coordinateSpace": "world",
            "incomplete": False, "meshes": [MESH]}), [MESH])

    def test_allow_open_and_force_cannot_override_missing_completeness(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "incomplete-without-flag.json"
            destination = root / "model.obj"
            sentinel = b"keep existing geometry output"
            destination.write_bytes(sentinel)
            source.write_text(json.dumps({
                "schemaVersion": 1, "coordinateSpace": "world",
                "meshes": [MESH],
            }), encoding="utf-8")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                status = print_export.main([
                    str(source), "--out", str(destination),
                    "--allow-open", "--force",
                ])
            self.assertEqual(status, 2, errors.getvalue())
            self.assertEqual(destination.read_bytes(), sentinel)
            self.assertIn("incomplete", errors.getvalue())

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
