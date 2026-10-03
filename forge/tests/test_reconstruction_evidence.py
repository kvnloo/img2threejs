import hashlib
import json
import struct
import zlib
from pathlib import Path

import tempfile
import unittest

from forge.stage1_intake.reconstruction_evidence import (
    EvidenceBundleError,
    load_bundle,
    load_optional_bundle,
)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _png(width: int, height: int, bit_depth: int, color_type: int) -> bytes:
    channels = {0: 1, 2: 3}[color_type]
    bytes_per_sample = bit_depth // 8
    row = b"\x00" + (b"\x00" * (width * channels * bytes_per_sample))
    raw = row * height
    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def _write_artifact(root: Path, name: str, payload: bytes) -> str:
    path = root / name
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _valid_bundle(root: Path) -> Path:
    reference = _png(2, 2, 8, 2)
    depth = _png(2, 2, 16, 0)
    mask = _png(2, 2, 8, 0)
    manifest = {
        "schemaVersion": 1,
        "kind": "reconstruction-evidence",
        "bundleId": "chair-0123456789abcdef",
        "producer": {
            "runtime": "ComfyUI",
            "node": "ReconstructionEvidenceBundle",
            "workflowShapeSha256": "a" * 64,
        },
        "artifacts": [
            {
                "role": "reference",
                "state": "measured",
                "relativePath": "reference.png",
                "sha256": _write_artifact(root, "reference.png", reference),
                "dimensions": {"width": 2, "height": 2},
                "encoding": "rgb8-png",
                "provenance": {"sourceType": "DA3_GEOMETRY.image"},
            },
            {
                "role": "depth",
                "state": "inferred",
                "relativePath": "depth.png",
                "sha256": _write_artifact(root, "depth.png", depth),
                "dimensions": {"width": 2, "height": 2},
                "encoding": "relative-linear-u16-png",
                "provenance": {"sourceType": "DA3_GEOMETRY", "mode": "mono"},
                "sourceRange": {"min": 1.0, "max": 5.0},
                "ordering": "lower-value-nearer",
            },
            {
                "role": "foreground-mask",
                "state": "inferred",
                "relativePath": "foreground-mask.png",
                "sha256": _write_artifact(root, "foreground-mask.png", mask),
                "dimensions": {"width": 2, "height": 2},
                "encoding": "mask-u8-png-white-is-1",
                "provenance": {"sourceType": "MASK"},
            },
        ],
        "limitations": ["Depth is inferred evidence."],
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


class ReconstructionEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp_path = Path(temporary.name) / "bundle"
        self.tmp_path.mkdir()

    def test_load_optional_bundle_preserves_no_evidence_path(self):
        self.assertIsNone(load_optional_bundle(None))

    def test_valid_bundle_verifies_hashes_dimensions_and_safe_receipt(self):
        manifest_path = _valid_bundle(self.tmp_path)

        bundle = load_bundle(manifest_path)

        self.assertEqual(bundle.bundle_id, "chair-0123456789abcdef")
        self.assertEqual(len(bundle.artifacts), 3)
        self.assertEqual(bundle.by_role("depth")[0].metadata["sourceRange"], {"min": 1.0, "max": 5.0})
        receipt = bundle.receipt()
        self.assertEqual(receipt["manifestSha256"], hashlib.sha256(manifest_path.read_bytes()).hexdigest())
        self.assertTrue(all("path" not in artifact for artifact in receipt["artifacts"]))
        self.assertEqual(receipt["artifacts"][0]["relativePath"], "reference.png")

    def test_rejects_artifact_path_traversal(self):
        manifest_path = _valid_bundle(self.tmp_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        outside = self.tmp_path.parent / "outside.png"
        outside.write_bytes(_png(2, 2, 8, 2))
        manifest["artifacts"][0]["relativePath"] = "../outside.png"
        manifest["artifacts"][0]["sha256"] = hashlib.sha256(outside.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(EvidenceBundleError, "within the bundle"):
            load_bundle(manifest_path)

    def test_rejects_hash_mismatch(self):
        manifest_path = _valid_bundle(self.tmp_path)
        (self.tmp_path / "foreground-mask.png").write_bytes(_png(3, 2, 8, 0))

        with self.assertRaisesRegex(EvidenceBundleError, "hash mismatch"):
            load_bundle(manifest_path)

    def test_rejects_depth_png_that_is_not_16_bit_grayscale(self):
        manifest_path = _valid_bundle(self.tmp_path)
        wrong_depth = _png(2, 2, 8, 0)
        (self.tmp_path / "depth.png").write_bytes(wrong_depth)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"][1]["sha256"] = hashlib.sha256(wrong_depth).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(EvidenceBundleError, "bitDepth=8"):
            load_bundle(manifest_path)

    def test_rejects_required_artifact_dimension_disagreement(self):
        manifest_path = _valid_bundle(self.tmp_path)
        wrong_mask = _png(3, 2, 8, 0)
        (self.tmp_path / "foreground-mask.png").write_bytes(wrong_mask)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"][2]["sha256"] = hashlib.sha256(wrong_mask).hexdigest()
        manifest["artifacts"][2]["dimensions"]["width"] = 3
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(EvidenceBundleError, "must share dimensions"):
            load_bundle(manifest_path)

    def test_rejects_unknown_producer_fields(self):
        manifest_path = _valid_bundle(self.tmp_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["producer"]["secret"] = "must-not-propagate"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(EvidenceBundleError, "unknown key"):
            load_bundle(manifest_path)
