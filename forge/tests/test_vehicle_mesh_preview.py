"""Offline viewer input validation: no unsafe/partial evidence can become a 3D preview."""
from __future__ import annotations

import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "integrations" / "vehicle_form" / "vehicle_mesh_preview.py"
module_spec = importlib.util.spec_from_file_location("vehicle_mesh_preview", SOURCE)
preview = importlib.util.module_from_spec(module_spec)
assert module_spec.loader
module_spec.loader.exec_module(preview)


def mesh(name="vehicle-body"):
    return {"name": name, "vertices": [[-1, 0, -1], [0, 0, 1], [1, 0, 0]], "indices": [0, 1, 2]}


def evidence(*meshes):
    return {"coordinateSpace": "world", "incomplete": False,
            "skippedMeshes": [], "meshes": list(meshes) or [mesh()]}


def gate(passed):
    return {"passed": passed, "stations": [
        {"id": "nose", "normalizedWidthError": 0.01 if passed else 0.5},
        {"id": "tail", "normalizedWidthError": 0.0143 if passed else 0.2},
    ]}


def png_chunk(typ: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data))


def png() -> bytes:
    return (preview.PNG_SIGNATURE + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(b"\x00\x00\xff\x00")) + png_chunk(b"IEND", b""))


class PreviewValidation(unittest.TestCase):
    def test_accepts_complete_world_space_mesh_and_embeds_browser_ui(self):
        page = preview.build_page(evidence(mesh()), evidence(mesh()), png(), gate(True), gate(False))
        self.assertIn('id="matched"', page)
        self.assertIn('id="stadium"', page)
        self.assertIn('data-view="top"', page)
        self.assertIn('1.43%', page)
        self.assertIn('50.0%', page)
        self.assertIn('window.__VEHICLE_PREVIEW_READY__=true', page)
        self.assertNotIn('<script src=', page)

    def test_untrusted_mesh_names_do_not_inject_html_script(self):
        malicious = '</script><script>window.stolen=true</script>'
        page = preview.build_page(evidence(mesh(), mesh(malicious)), evidence(mesh()), png(), gate(True), gate(False))
        self.assertNotIn(malicious, page)
        self.assertIn('\\u003c/script\\u003e', page)

    def test_requires_explicit_complete_world_geometry(self):
        cases = [
            {**evidence(mesh()), "incomplete": True},
            {**evidence(mesh()), "incomplete": "false"},
            {**evidence(mesh()), "incomplete": None},
            {**evidence(mesh()), "coordinateSpace": "local"},
            {**evidence(mesh()), "skippedMeshes": [{"name": "wheel", "reason": "vertex-budget"}]},
            {**evidence(mesh()), "skippedMeshes": None},
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(preview.PreviewInputError):
                    preview.validated_meshes(case)

    def test_missing_and_malformed_faces_cannot_render(self):
        bad_meshes = [
            {**mesh(), "vertices": []},
            {**mesh(), "vertices": [[0, 0], [1, 0, 0], [1, 1, 0]]},
            {**mesh(), "vertices": [[0, 0, 0], [1, float('nan'), 0], [1, 1, 0]]},
            {**mesh(), "indices": [0, 1]},
            {**mesh(), "indices": [0, 1, 3]},
            {**mesh(), "indices": [0, 1, True]},
        ]
        for value in bad_meshes:
            with self.subTest(value=value):
                with self.assertRaises(preview.PreviewInputError):
                    preview.validated_meshes(evidence(value))

    def test_requires_actual_matching_and_rejected_gate_verdicts(self):
        with self.assertRaises(preview.PreviewInputError):
            preview.build_page(evidence(mesh()), evidence(mesh()), png(), gate(True), gate(True))
        with self.assertRaises(preview.PreviewInputError):
            preview.build_page(evidence(mesh()), evidence(mesh()), png(), gate(False), gate(False))
        malformed = gate(True)
        malformed["stations"][0]["normalizedWidthError"] = float('nan')
        with self.assertRaises(preview.PreviewInputError):
            preview.build_page(evidence(mesh()), evidence(mesh()), png(), malformed, gate(False))

    def test_refuses_missing_scored_body(self):
        with self.assertRaises(preview.PreviewInputError):
            preview.build_page(evidence(mesh("floor")), evidence(mesh()), png(), gate(True), gate(False))

    def test_cli_generates_offline_html_and_removes_stale_output_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            matching = directory / "match.json"
            stadium = directory / "stadium.json"
            matchgate = directory / "matchgate.json"
            failgate = directory / "failgate.json"
            image = directory / "reference.png"
            output = directory / "viewer.html"
            for path, blob in ((matching, evidence(mesh())), (stadium, evidence(mesh())),
                               (matchgate, gate(True)), (failgate, gate(False))):
                path.write_text(json.dumps(blob), encoding="utf-8")
            image.write_bytes(png())
            command = [sys.executable, str(SOURCE), "--matching", str(matching), "--stadium", str(stadium),
                       "--reference", str(image), "--matching-report", str(matchgate),
                       "--stadium-report", str(failgate), "--out", str(output)]
            success = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertIn('vehicle-body', output.read_text(encoding="utf-8"))
            matching.write_text(json.dumps({**evidence(mesh()), "incomplete": True}), encoding="utf-8")
            failure = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(failure.returncode, 2)
            self.assertIn("incomplete", failure.stderr)
            self.assertFalse(output.exists(), "failed retry left a stale success-looking preview")

    def test_png_validation_rejects_wrong_magic_and_bad_dimensions(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "reference.png"
            path.write_bytes(b"not an image")
            with self.assertRaises(preview.PreviewInputError):
                preview._validate_png(path)
            malformed = preview.PNG_SIGNATURE + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 0, 1, 8, 2, 0, 0, 0))
            path.write_bytes(malformed + png_chunk(b"IDAT", b"x") + png_chunk(b"IEND", b""))
            with self.assertRaises(preview.PreviewInputError):
                preview._validate_png(path)
            valid = png()
            path.write_bytes(valid[:-6])
            with self.assertRaisesRegex(preview.PreviewInputError, "truncated|missing"):
                preview._validate_png(path)
            corrupt = bytearray(valid)
            corrupt[-16] ^= 1
            path.write_bytes(corrupt)
            with self.assertRaisesRegex(preview.PreviewInputError, "checksum"):
                preview._validate_png(path)


if __name__ == "__main__":
    unittest.main()
