import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

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


def test_load_optional_bundle_preserves_no_evidence_path():
    assert load_optional_bundle(None) is None


def test_valid_bundle_verifies_hashes_dimensions_and_safe_receipt(tmp_path):
    manifest_path = _valid_bundle(tmp_path)

    bundle = load_bundle(manifest_path)

    assert bundle.bundle_id == "chair-0123456789abcdef"
    assert len(bundle.artifacts) == 3
    assert bundle.by_role("depth")[0].metadata["sourceRange"] == {"min": 1.0, "max": 5.0}
    receipt = bundle.receipt()
    assert receipt["manifestSha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert all("path" not in artifact for artifact in receipt["artifacts"])
    assert receipt["artifacts"][0]["relativePath"] == "reference.png"


def test_rejects_artifact_path_traversal(tmp_path):
    manifest_path = _valid_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(_png(2, 2, 8, 2))
    manifest["artifacts"][0]["relativePath"] = "../outside.png"
    manifest["artifacts"][0]["sha256"] = hashlib.sha256(outside.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidenceBundleError, match="within the bundle"):
        load_bundle(manifest_path)


def test_rejects_hash_mismatch(tmp_path):
    manifest_path = _valid_bundle(tmp_path)
    (tmp_path / "foreground-mask.png").write_bytes(_png(3, 2, 8, 0))

    with pytest.raises(EvidenceBundleError, match="hash mismatch"):
        load_bundle(manifest_path)


def test_rejects_depth_png_that_is_not_16_bit_grayscale(tmp_path):
    manifest_path = _valid_bundle(tmp_path)
    wrong_depth = _png(2, 2, 8, 0)
    (tmp_path / "depth.png").write_bytes(wrong_depth)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][1]["sha256"] = hashlib.sha256(wrong_depth).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidenceBundleError, match="bitDepth=8"):
        load_bundle(manifest_path)


def test_rejects_required_artifact_dimension_disagreement(tmp_path):
    manifest_path = _valid_bundle(tmp_path)
    wrong_mask = _png(3, 2, 8, 0)
    (tmp_path / "foreground-mask.png").write_bytes(wrong_mask)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][2]["sha256"] = hashlib.sha256(wrong_mask).hexdigest()
    manifest["artifacts"][2]["dimensions"]["width"] = 3
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidenceBundleError, match="must share dimensions"):
        load_bundle(manifest_path)


def test_rejects_unknown_producer_fields(tmp_path):
    manifest_path = _valid_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["producer"]["secret"] = "must-not-propagate"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidenceBundleError, match="unknown key"):
        load_bundle(manifest_path)
