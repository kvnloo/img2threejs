#!/usr/bin/env python3
"""Validate and load backend-neutral reconstruction evidence bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final, Mapping, Sequence


SCHEMA_VERSION: Final = 1
KIND: Final = "reconstruction-evidence"
ALLOWED_ROLES: Final = {
    "reference",
    "depth",
    "foreground-mask",
    "material-mask",
    "normal",
    "edge",
    "alternate-view",
}
ALLOWED_STATES: Final = {"measured", "inferred", "generated"}
REQUIRED_SINGLETON_ROLES: Final = {"reference", "depth", "foreground-mask"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,96}$")


@dataclass(frozen=True, slots=True)
class EvidenceBundleError(ValueError):
    field: str
    detail: str

    def __str__(self) -> str:
        return f"invalid reconstruction evidence {self.field}: {self.detail}"


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    role: str
    state: str
    relative_path: str
    path: Path
    sha256: str
    width: int
    height: int
    encoding: str
    provenance: Mapping[str, Any]
    metadata: Mapping[str, Any]

    def receipt(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "state": self.state,
            "relativePath": self.relative_path,
            "sha256": self.sha256,
            "dimensions": {"width": self.width, "height": self.height},
            "encoding": self.encoding,
        }


@dataclass(frozen=True, slots=True)
class ReconstructionEvidenceBundle:
    manifest_path: Path
    manifest_sha256: str
    bundle_id: str
    producer: Mapping[str, Any]
    artifacts: tuple[EvidenceArtifact, ...]
    limitations: tuple[str, ...]

    def by_role(self, role: str) -> tuple[EvidenceArtifact, ...]:
        return tuple(item for item in self.artifacts if item.role == role)

    def receipt(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "kind": KIND,
            "bundleId": self.bundle_id,
            "manifestSha256": self.manifest_sha256,
            "producer": dict(self.producer),
            "artifacts": [item.receipt() for item in self.artifacts],
        }


def load_optional_bundle(manifest_path: str | Path | None) -> ReconstructionEvidenceBundle | None:
    if manifest_path is None:
        return None
    return load_bundle(manifest_path)


def load_bundle(manifest_path: str | Path) -> ReconstructionEvidenceBundle:
    path = Path(manifest_path)
    try:
        manifest_bytes = path.read_bytes()
    except OSError as exc:
        raise EvidenceBundleError("manifest", str(exc)) from exc

    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceBundleError("manifest", "must be valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise EvidenceBundleError("manifest", "must be a JSON object")
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise EvidenceBundleError("schemaVersion", f"must equal {SCHEMA_VERSION}")
    if manifest.get("kind") != KIND:
        raise EvidenceBundleError("kind", f"must equal {KIND!r}")

    bundle_id = manifest.get("bundleId")
    if not isinstance(bundle_id, str) or not _BUNDLE_ID_RE.fullmatch(bundle_id):
        raise EvidenceBundleError("bundleId", "must be a bounded filename-safe identifier")

    producer = manifest.get("producer")
    if not isinstance(producer, dict):
        raise EvidenceBundleError("producer", "must be an object")
    if not isinstance(producer.get("runtime"), str) or not producer["runtime"].strip():
        raise EvidenceBundleError("producer.runtime", "must be a non-empty string")
    if not isinstance(producer.get("node"), str) or not producer["node"].strip():
        raise EvidenceBundleError("producer.node", "must be a non-empty string")
    shape_hash = producer.get("workflowShapeSha256")
    if shape_hash is not None and (not isinstance(shape_hash, str) or not _SHA256_RE.fullmatch(shape_hash)):
        raise EvidenceBundleError("producer.workflowShapeSha256", "must be a lowercase SHA-256 hex digest")

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise EvidenceBundleError("artifacts", "must be a non-empty array")

    root = path.parent.resolve()
    artifacts = tuple(_load_artifact(root, index, raw) for index, raw in enumerate(raw_artifacts))

    for role in REQUIRED_SINGLETON_ROLES:
        matches = [item for item in artifacts if item.role == role]
        if len(matches) != 1:
            raise EvidenceBundleError("artifacts", f"requires exactly one {role!r} artifact")

    dimensions = {(item.width, item.height) for item in artifacts if item.role in REQUIRED_SINGLETON_ROLES | {"material-mask"}}
    if len(dimensions) != 1:
        raise EvidenceBundleError("artifacts", "reference/depth/mask artifacts must share dimensions in v0")

    limitations_raw = manifest.get("limitations", [])
    if not isinstance(limitations_raw, list) or not all(isinstance(item, str) for item in limitations_raw):
        raise EvidenceBundleError("limitations", "must be an array of strings when present")

    return ReconstructionEvidenceBundle(
        manifest_path=path.resolve(),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        bundle_id=bundle_id,
        producer=dict(producer),
        artifacts=artifacts,
        limitations=tuple(limitations_raw),
    )


def _load_artifact(root: Path, index: int, raw: Any) -> EvidenceArtifact:
    field = f"artifacts[{index}]"
    if not isinstance(raw, dict):
        raise EvidenceBundleError(field, "must be an object")

    role = raw.get("role")
    if role not in ALLOWED_ROLES:
        raise EvidenceBundleError(f"{field}.role", f"must be one of {sorted(ALLOWED_ROLES)}")
    state = raw.get("state")
    if state not in ALLOWED_STATES:
        raise EvidenceBundleError(f"{field}.state", f"must be one of {sorted(ALLOWED_STATES)}")

    relative_path = raw.get("relativePath")
    if not isinstance(relative_path, str) or not relative_path:
        raise EvidenceBundleError(f"{field}.relativePath", "must be a non-empty relative POSIX path")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise EvidenceBundleError(f"{field}.relativePath", "must stay within the bundle directory")
    resolved = (root / Path(*pure.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise EvidenceBundleError(f"{field}.relativePath", "resolves outside the bundle directory") from exc
    if not resolved.is_file():
        raise EvidenceBundleError(f"{field}.relativePath", "artifact file does not exist")

    expected_hash = raw.get("sha256")
    if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
        raise EvidenceBundleError(f"{field}.sha256", "must be a lowercase SHA-256 hex digest")
    actual_hash = _sha256_file(resolved)
    if actual_hash != expected_hash:
        raise EvidenceBundleError(f"{field}.sha256", f"hash mismatch for {relative_path}")

    dimensions = raw.get("dimensions")
    if not isinstance(dimensions, dict):
        raise EvidenceBundleError(f"{field}.dimensions", "must be an object")
    width = _positive_int(dimensions.get("width"), f"{field}.dimensions.width")
    height = _positive_int(dimensions.get("height"), f"{field}.dimensions.height")

    encoding = raw.get("encoding")
    if not isinstance(encoding, str) or not encoding:
        raise EvidenceBundleError(f"{field}.encoding", "must be a non-empty string")

    provenance = raw.get("provenance")
    if not isinstance(provenance, dict):
        raise EvidenceBundleError(f"{field}.provenance", "must be an object")

    if resolved.suffix.lower() == ".png":
        png_width, png_height, bit_depth, color_type = _png_header(resolved)
        if (png_width, png_height) != (width, height):
            raise EvidenceBundleError(f"{field}.dimensions", "do not match the PNG IHDR dimensions")
        _validate_png_encoding(field, role, encoding, bit_depth, color_type)

    metadata = {
        key: value
        for key, value in raw.items()
        if key not in {"role", "state", "relativePath", "sha256", "dimensions", "encoding", "provenance"}
    }
    if role == "depth":
        source_range = metadata.get("sourceRange")
        if not isinstance(source_range, dict):
            raise EvidenceBundleError(f"{field}.sourceRange", "is required for normalized depth")
        minimum = _finite_number(source_range.get("min"), f"{field}.sourceRange.min")
        maximum = _finite_number(source_range.get("max"), f"{field}.sourceRange.max")
        if maximum < minimum:
            raise EvidenceBundleError(f"{field}.sourceRange", "max must be greater than or equal to min")
        if metadata.get("ordering") != "lower-value-nearer":
            raise EvidenceBundleError(f"{field}.ordering", "must equal 'lower-value-nearer' in v0")

    return EvidenceArtifact(
        role=role,
        state=state,
        relative_path=relative_path,
        path=resolved,
        sha256=expected_hash,
        width=width,
        height=height,
        encoding=encoding,
        provenance=dict(provenance),
        metadata=metadata,
    )


def _validate_png_encoding(field: str, role: str, encoding: str, bit_depth: int, color_type: int) -> None:
    expected = {
        "reference": ("rgb8-png", 8, {2, 6}),
        "depth": ("relative-linear-u16-png", 16, {0}),
        "foreground-mask": ("mask-u8-png-white-is-1", 8, {0}),
        "material-mask": ("mask-u8-png-white-is-1", 8, {0}),
    }.get(role)
    if expected is None:
        return
    expected_encoding, expected_bits, expected_color_types = expected
    if encoding != expected_encoding:
        raise EvidenceBundleError(f"{field}.encoding", f"{role} must use {expected_encoding!r} in v0")
    if bit_depth != expected_bits or color_type not in expected_color_types:
        raise EvidenceBundleError(
            f"{field}.encoding",
            f"PNG encoding does not match {expected_encoding!r} (bitDepth={bit_depth}, colorType={color_type})",
        )


def _png_header(path: Path) -> tuple[int, int, int, int]:
    try:
        header = path.read_bytes()[:26]
    except OSError as exc:
        raise EvidenceBundleError(str(path), str(exc)) from exc
    if len(header) < 26 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise EvidenceBundleError(str(path), "expected a PNG with an IHDR header")
    width, height = struct.unpack(">II", header[16:24])
    return width, height, header[24], header[25]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvidenceBundleError(field, "must be a positive integer")
    return value


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvidenceBundleError(field, "must be a finite number")
    return float(value)


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        bundle = load_bundle(args.manifest)
    except EvidenceBundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = bundle.receipt()
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"{bundle.bundle_id}: {len(bundle.artifacts)} verified artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
