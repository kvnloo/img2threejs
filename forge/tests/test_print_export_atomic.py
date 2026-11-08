"""Atomic print-export publication: failed writers must not leave slicer artifacts."""
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


# A closed, outward-oriented tetrahedron; avoids any upstream fixture dependency.
FACES = [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]


def tetra(size=1.0):
    return {
        "name": "tetra",
        "vertices": [
            [0, 0, 0], [size, 0, 0], [0, size, 0], [0, 0, size],
        ],
        "indices": FACES,
    }


class AtomicPublicationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def _leftovers(self):
        return list(self.folder.glob(".*.tmp"))

    def _broken_writer(self, path, vertices, triangles, *, name):
        path.write_bytes(b"partial STL bytes")
        raise OSError("simulated disk failure")

    def _run(self, size, *, existing=None):
        input_path = self.folder / "mesh.json"
        destination = self.folder / "solid.stl"
        input_path.write_text(json.dumps({"meshes": [tetra(size)]}), encoding="utf-8")
        if existing is not None:
            destination.write_bytes(existing)
        stderr = io.StringIO()
        stdout = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            code = print_export.main(
                [str(input_path), "--out", str(destination)] +
                (["--force"] if existing is not None else [])
            )
        return code, destination, stderr.getvalue()

    def test_staging_error_leaves_no_partial_file(self):
        destination = self.folder / "model.stl"
        with self.assertRaisesRegex(OSError, "simulated disk failure"):
            print_export.write_export_atomically(
                destination, self._broken_writer, [], [], name="test"
            )
        self.assertFalse(destination.exists())
        self.assertEqual(self._leftovers(), [])

    def test_staging_error_does_not_destroy_an_existing_export(self):
        destination = self.folder / "model.obj"
        destination.write_bytes(b"previous valid model")
        with self.assertRaisesRegex(OSError, "simulated disk failure"):
            print_export.write_export_atomically(
                destination, self._broken_writer, [], [], name="test"
            )
        self.assertEqual(destination.read_bytes(), b"previous valid model")
        self.assertEqual(self._leftovers(), [])

    def test_float32_overflow_is_a_clean_cli_failure_with_no_stl(self):
        code, destination, stderr = self._run(1e40)
        self.assertEqual(code, 2, stderr)
        self.assertIn("print export write error:", stderr)
        self.assertFalse(destination.exists())
        self.assertEqual(self._leftovers(), [])

    def test_force_overflow_preserves_prior_export_bytes(self):
        sentinel = b"old export remains intact"
        code, destination, stderr = self._run(1e40, existing=sentinel)
        self.assertEqual(code, 2, stderr)
        self.assertEqual(destination.read_bytes(), sentinel)
        self.assertEqual(self._leftovers(), [])

    def test_successful_export_has_complete_binary_layout_without_temp_files(self):
        code, destination, stderr = self._run(1.0)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(destination.stat().st_size, 84 + len(FACES) * 50)
        self.assertEqual(self._leftovers(), [])


if __name__ == "__main__":
    unittest.main()
