#!/usr/bin/env python3
"""Write a self-contained, interactive viewer of two verified exported vehicle meshes.

The viewer draws the *existing* world-space triangle arrays with Canvas 2D, no
network or model downloads. This is visual inspection, NOT a visual-fidelity gate.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import zlib
from typing import Any

MAX_INPUT_BYTES = 15_000_000
MAX_VERTICES = 500_000
MAX_TRIANGLES = 500_000
MAX_MESHES = 2000
MAX_REFERENCE_BYTES = 4_000_000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TEMPLATE = Path(__file__).with_name("vehicle_mesh_preview.template.html")


class PreviewInputError(ValueError):
    """The supplied evidence cannot be safely visualized."""


def _read_json(path: Path) -> Any:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise PreviewInputError("JSON evidence exceeds maximum file size")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(PreviewInputError("non-finite JSON number")))


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validated_meshes(payload: Any) -> list[dict[str, Any]]:
    """Return only coordinates and connectivity; refuse truncated or partial evidence."""
    if not isinstance(payload, dict) or payload.get("incomplete") is not False:
        raise PreviewInputError("mesh export is missing or marked incomplete")
    if payload.get("coordinateSpace") != "world":
        raise PreviewInputError("mesh export must declare world-space coordinates")
    for key in ("skippedMeshes", "skipped"):
        if key in payload:
            omitted = payload[key]
            if not isinstance(omitted, list) or any(
                not isinstance(row, dict) or row.get("reason") not in {"hidden", "filtered"}
                for row in omitted
            ):
                raise PreviewInputError("active or unknown meshes were omitted")
    meshes = payload.get("meshes")
    if not isinstance(meshes, list) or not meshes or len(meshes) > MAX_MESHES:
        raise PreviewInputError("meshes must be a non-empty bounded list")
    vertices_total = triangles_total = 0
    result = []
    for mesh in meshes:
        if not isinstance(mesh, dict):
            raise PreviewInputError("mesh entry must be an object")
        name = mesh.get("name")
        vertices = mesh.get("vertices")
        indices = mesh.get("indices")
        if not isinstance(name, str) or not name or len(name) > 500:
            raise PreviewInputError("mesh name is invalid")
        if not isinstance(vertices, list) or len(vertices) < 3 or not isinstance(indices, list) or not indices or len(indices) % 3:
            raise PreviewInputError("mesh has no usable triangles")
        vertices_total += len(vertices)
        triangles_total += len(indices) // 3
        if vertices_total > MAX_VERTICES or triangles_total > MAX_TRIANGLES:
            raise PreviewInputError("geometry exceeds the preview budget")
        if any(
            not isinstance(point, list) or len(point) != 3 or not all(_finite_number(x) for x in point)
            for point in vertices
        ):
            raise PreviewInputError("mesh has malformed or non-finite coordinates")
        if any(type(index) is not int or index < 0 or index >= len(vertices) for index in indices):
            raise PreviewInputError("mesh has invalid triangle index")
        result.append({"name": name, "vertices": vertices, "indices": indices})
    return result


def _max_error(report: Any, *, expected_pass: bool) -> str:
    if not isinstance(report, dict) or report.get("passed") is not expected_pass:
        raise PreviewInputError("gate report does not match the expected verdict")
    rows = report.get("stations")
    if not isinstance(rows, list) or not rows:
        raise PreviewInputError("gate report has no scored stations")
    errors = [row.get("normalizedWidthError") for row in rows if isinstance(row, dict)]
    if len(errors) != len(rows) or not all(_finite_number(x) and 0 <= x <= 1 for x in errors):
        raise PreviewInputError("gate report contains invalid station errors")
    return str(round(100 * max(errors), 2))


def _validate_png(path: Path) -> bytes:
    if path.stat().st_size > MAX_REFERENCE_BYTES:
        raise PreviewInputError("reference image is too large for an offline viewer")
    png = path.read_bytes()
    if len(png) < 33 or png[:8] != PNG_SIGNATURE or png[12:16] != b"IHDR":
        raise PreviewInputError("reference screenshot is not a PNG")
    width, height = struct.unpack(">II", png[16:24])
    if not 0 < width <= 4096 or not 0 < height <= 4096:
        raise PreviewInputError("reference PNG has invalid dimensions")
    position = len(PNG_SIGNATURE)
    saw_image = saw_end = False
    while position < len(png):
        if len(png) - position < 12:
            raise PreviewInputError("truncated PNG chunk")
        length = int.from_bytes(png[position:position+4], "big")
        end = position + 12 + length
        if end > len(png):
            raise PreviewInputError("truncated PNG chunk")
        kind = png[position+4:position+8]
        contents = png[position+8:position+8+length]
        checksum = int.from_bytes(png[end-4:end], "big")
        if zlib.crc32(kind + contents) != checksum:
            raise PreviewInputError("reference PNG has a corrupt chunk checksum")
        if position == len(PNG_SIGNATURE) and (kind != b"IHDR" or length != 13):
            raise PreviewInputError("reference PNG has invalid header")
        if kind == b"IDAT":
            saw_image = True
        if kind == b"IEND":
            saw_end = length == 0 and end == len(png)
            break
        position = end
    if not saw_image or not saw_end:
        raise PreviewInputError("reference PNG is missing image data or final marker")
    return png


def build_page(matching: Any, stadium: Any, reference_png: bytes, matching_gate: Any, stadium_gate: Any) -> str:
    match_error = _max_error(matching_gate, expected_pass=True)
    fail_error = _max_error(stadium_gate, expected_pass=False)
    source = {
        "matching": validated_meshes(matching),
        "stadium": validated_meshes(stadium),
    }
    if not any(m["name"] == "vehicle-body" for m in source["matching"]):
        raise PreviewInputError("matching scene lacks the scored vehicle-body mesh")
    if not any(m["name"] == "vehicle-body" for m in source["stadium"]):
        raise PreviewInputError("failing scene lacks the scored vehicle-body mesh")
    # Prevent a mesh name such as '</script><script>...' from leaving the data literal.
    safe_json = json.dumps(source, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    safe_json = safe_json.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = TEMPLATE.read_text(encoding="utf-8")
    return (
        page.replace("__SCENE_JSON__", safe_json)
        .replace("__REF_PNG__", base64.b64encode(reference_png).decode("ascii"))
        .replace("__MATCH_ERR__", match_error)
        .replace("__FAIL_ERR__", fail_error)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matching", type=Path, required=True, help="complete matching meshes.json")
    parser.add_argument("--stadium", type=Path, required=True, help="complete rejected meshes.json")
    parser.add_argument("--reference", type=Path, required=True, help="synthetic reference-top.png")
    parser.add_argument("--matching-report", type=Path, required=True, help="passing geometry gate JSON")
    parser.add_argument("--stadium-report", type=Path, required=True, help="failing geometry gate JSON")
    parser.add_argument("--out", type=Path, required=True, help="standalone interactive HTML")
    args = parser.parse_args(argv)
    # A failed new run must not leave a stale success-looking visualization behind.
    args.out.unlink(missing_ok=True)
    try:
        html = build_page(
            _read_json(args.matching), _read_json(args.stadium), _validate_png(args.reference),
            _read_json(args.matching_report), _read_json(args.stadium_report),
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix=".vehicle-preview-", suffix=".tmp",
                                         dir=args.out.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(html)
        try:
            os.replace(temporary, args.out)
        finally:
            temporary.unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError, PreviewInputError, UnicodeError, OverflowError) as error:
        print(f"vehicle preview error: {error}", file=sys.stderr)
        return 2
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
