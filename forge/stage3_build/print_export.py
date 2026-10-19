#!/usr/bin/env python3
"""Bake exported world-space meshes into one printable STL or OBJ, with a manifold gate.

Input is the ``meshes.json`` shape already consumed by ``stage4_review/self_intersection.py``:
a list of meshes (or ``{"meshes": [...]}``), each with world-space ``vertices`` (``[[x, y, z], ...]``)
and triangle ``indices`` (flat or ``[[a, b, c], ...]``; omitted means non-indexed triangles).

The exporter

1. merges every mesh into a single triangle soup and welds coincident vertices (``--weld``),
2. drops degenerate (zero-area / repeated-index) triangles and reports how many,
3. checks every merged shell is closed and two-manifold with consistent winding,
4. scales so the longest bounding-box edge equals ``--longest-edge-mm`` (optional),
5. writes binary STL or OBJ, and a JSON report.

It fails closed: a mesh with boundary edges, non-manifold edges, or inconsistently wound faces is
NOT written unless ``--allow-open`` is passed, so a slicer never silently receives a broken model.
A shell with negative signed volume is reported as inside-out (flipped normals).

What this does not do: boolean union of overlapping parts. A procedural ``THREE.Group`` usually
overlaps its parts (embedded attachments), so each part may be a closed shell while the assembly
contains internal faces. Most slicers union overlapping closed shells; the report counts shells so
the user can see what the slicer will receive. Wall-thickness analysis is out of scope and
reconstructed hidden faces (single-image input) are approximations; see docs/PRINT_EXPORT.md.

Pure Python 3.10+ stdlib.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DEFAULT_WELD = 1e-6
FORMATS = ("stl", "obj")

Vec = tuple[float, float, float]


class PrintExportError(ValueError):
    """Input that cannot be exported at all (not merely non-watertight)."""


def load_meshes(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("meshes"), list):
            return payload["meshes"]
        if isinstance(payload.get("vertices"), list):
            return [payload]
    if isinstance(payload, list):
        return payload
    raise PrintExportError("input must be a mesh, a list of meshes, or an object with a meshes list")


def _vertex(value: Any, mesh_name: str) -> Vec:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise PrintExportError(f"{mesh_name}: vertices must be [x, y, z] triples")
    try:
        x, y, z = (float(component) for component in value[:3])
    except (TypeError, ValueError) as error:
        raise PrintExportError(f"{mesh_name}: non-numeric vertex {value!r}") from error
    if not all(math.isfinite(c) for c in (x, y, z)):
        raise PrintExportError(f"{mesh_name}: non-finite vertex {value!r}")
    return (x, y, z)


def _triangles(mesh: dict[str, Any], vertex_count: int, mesh_name: str) -> list[tuple[int, int, int]]:
    raw = mesh.get("indices")
    if raw is None:
        if vertex_count % 3:
            raise PrintExportError(f"{mesh_name}: non-indexed vertex count {vertex_count} is not a multiple of 3")
        flat: list[Any] = list(range(vertex_count))
    elif isinstance(raw, list) and raw and isinstance(raw[0], (list, tuple)):
        flat = [index for triangle in raw for index in triangle]
        if any(len(triangle) != 3 for triangle in raw):
            raise PrintExportError(f"{mesh_name}: nested indices must be triangles")
    elif isinstance(raw, list):
        flat = raw
    else:
        raise PrintExportError(f"{mesh_name}: indices must be a list")
    if len(flat) % 3:
        raise PrintExportError(f"{mesh_name}: index count {len(flat)} is not a multiple of 3")
    triangles = []
    for offset in range(0, len(flat), 3):
        triangle = []
        for index in flat[offset:offset + 3]:
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < vertex_count:
                raise PrintExportError(f"{mesh_name}: index {index!r} out of range for {vertex_count} vertices")
            triangle.append(index)
        triangles.append((triangle[0], triangle[1], triangle[2]))
    return triangles


def merge_meshes(meshes: list[dict[str, Any]], *, weld: float = DEFAULT_WELD) -> dict[str, Any]:
    """Merge meshes into one welded triangle list. Returns vertices, triangles and counters."""
    if weld <= 0 or not math.isfinite(weld):
        raise PrintExportError("--weld must be a positive finite distance")
    if not meshes:
        raise PrintExportError("no meshes to export")
    vertices: list[Vec] = []
    lookup: dict[tuple[int, int, int], int] = {}
    triangles: list[tuple[int, int, int]] = []
    degenerate = 0
    source_triangles = 0
    for position, mesh in enumerate(meshes):
        if not isinstance(mesh, dict):
            raise PrintExportError(f"mesh #{position} is not an object")
        name = str(mesh.get("name") or mesh.get("id") or f"mesh#{position}")
        raw_vertices = mesh.get("vertices")
        if not isinstance(raw_vertices, list) or not raw_vertices:
            raise PrintExportError(f"{name}: no vertices (refusing to export empty geometry)")
        local = [_vertex(value, name) for value in raw_vertices]
        remap = []
        for point in local:
            key = (round(point[0] / weld), round(point[1] / weld), round(point[2] / weld))
            index = lookup.get(key)
            if index is None:
                index = lookup[key] = len(vertices)
                vertices.append(point)
            remap.append(index)
        for a, b, c in _triangles(mesh, len(local), name):
            source_triangles += 1
            triangle = (remap[a], remap[b], remap[c])
            if len(set(triangle)) < 3 or _area2(vertices, triangle) <= 0.0:
                degenerate += 1
                continue
            triangles.append(triangle)
    if not triangles:
        raise PrintExportError("every triangle was degenerate; nothing to export")
    return {
        "vertices": vertices,
        "triangles": triangles,
        "sourceMeshCount": len(meshes),
        "sourceTriangleCount": source_triangles,
        "degenerateTrianglesDropped": degenerate,
    }


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _area2(vertices: list[Vec], triangle: tuple[int, int, int]) -> float:
    a, b, c = (vertices[i] for i in triangle)
    n = _cross(_sub(b, a), _sub(c, a))
    return math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])


def _normal(vertices: list[Vec], triangle: tuple[int, int, int]) -> Vec:
    a, b, c = (vertices[i] for i in triangle)
    n = _cross(_sub(b, a), _sub(c, a))
    length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1.0
    return (n[0] / length, n[1] / length, n[2] / length)


def analyze_manifold(vertices: list[Vec], triangles: list[tuple[int, int, int]]) -> dict[str, Any]:
    """Edge-use analysis plus per-shell closure, winding and signed volume."""
    undirected: Counter[tuple[int, int]] = Counter()
    directed: Counter[tuple[int, int]] = Counter()
    for a, b, c in triangles:
        for u, v in ((a, b), (b, c), (c, a)):
            directed[(u, v)] += 1
            undirected[(u, v) if u < v else (v, u)] += 1
    boundary = sorted(edge for edge, count in undirected.items() if count == 1)
    non_manifold = sorted(edge for edge, count in undirected.items() if count > 2)
    # A closed, consistently wound 2-manifold uses each directed edge once and its reverse once.
    misoriented = sorted(
        edge for edge, count in undirected.items()
        if count == 2 and not (directed.get(edge, 0) == 1 and directed.get((edge[1], edge[0]), 0) == 1)
    )

    # Shells: connected components over shared edges.
    parent = list(range(len(triangles)))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    by_edge: dict[tuple[int, int], int] = {}
    for face, (a, b, c) in enumerate(triangles):
        for u, v in ((a, b), (b, c), (c, a)):
            key = (u, v) if u < v else (v, u)
            other = by_edge.setdefault(key, face)
            if other != face:
                root_a, root_b = find(face), find(other)
                if root_a != root_b:
                    parent[root_b] = root_a
    shells: dict[int, list[int]] = defaultdict(list)
    for face in range(len(triangles)):
        shells[find(face)].append(face)

    bad_edges = set(boundary) | set(non_manifold) | set(misoriented)
    shell_reports = []
    for faces in sorted(shells.values(), key=lambda group: (-len(group), group[0])):
        volume = 0.0
        closed = True
        for face in faces:
            a, b, c = (vertices[i] for i in triangles[face])
            volume += (a[0] * (b[1] * c[2] - b[2] * c[1])
                       - a[1] * (b[0] * c[2] - b[2] * c[0])
                       + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
            if closed:
                x, y, z = triangles[face]
                for u, v in ((x, y), (y, z), (z, x)):
                    if ((u, v) if u < v else (v, u)) in bad_edges:
                        closed = False
                        break
        shell_reports.append({
            "triangleCount": len(faces),
            "closed": closed,
            "signedVolume": volume,
            "insideOut": closed and volume < 0.0,
        })
    watertight = not boundary and not non_manifold and not misoriented
    return {
        "watertight": watertight,
        "boundaryEdgeCount": len(boundary),
        "nonManifoldEdgeCount": len(non_manifold),
        "misorientedEdgeCount": len(misoriented),
        "boundaryEdgeSample": [list(edge) for edge in boundary[:8]],
        "nonManifoldEdgeSample": [list(edge) for edge in non_manifold[:8]],
        "shellCount": len(shell_reports),
        "insideOutShellCount": sum(shell["insideOut"] for shell in shell_reports),
        "shells": shell_reports,
    }


def bounds(vertices: list[Vec]) -> tuple[Vec, Vec]:
    low = tuple(min(point[axis] for point in vertices) for axis in range(3))
    high = tuple(max(point[axis] for point in vertices) for axis in range(3))
    return low, high  # type: ignore[return-value]


def scale_to_longest_edge(vertices: list[Vec], longest_edge: float) -> tuple[list[Vec], float]:
    if longest_edge <= 0 or not math.isfinite(longest_edge):
        raise PrintExportError("--longest-edge-mm must be a positive finite number")
    low, high = bounds(vertices)
    extent = max(high[axis] - low[axis] for axis in range(3))
    if extent <= 0:
        raise PrintExportError("model has zero extent; cannot scale")
    factor = longest_edge / extent
    return [(x * factor, y * factor, z * factor) for x, y, z in vertices], factor


def write_stl(path: Path, vertices: list[Vec], triangles: list[tuple[int, int, int]], *, name: str = "img2threejs") -> None:
    header = f"img2threejs print export: {name}".encode("ascii", "replace")[:80].ljust(80, b"\0")
    with path.open("wb") as stream:
        stream.write(header)
        stream.write(struct.pack("<I", len(triangles)))
        for triangle in triangles:
            stream.write(struct.pack("<3f", *_normal(vertices, triangle)))
            for index in triangle:
                stream.write(struct.pack("<3f", *vertices[index]))
            stream.write(b"\0\0")


def write_obj(path: Path, vertices: list[Vec], triangles: list[tuple[int, int, int]], *, name: str = "img2threejs") -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(f"# img2threejs print export: {name}\n")
        stream.write(f"o {name}\n")
        for x, y, z in vertices:
            stream.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for a, b, c in triangles:
            stream.write(f"f {a + 1} {b + 1} {c + 1}\n")


def build_export(meshes: list[dict[str, Any]], *, weld: float = DEFAULT_WELD,
                 longest_edge_mm: float | None = None) -> dict[str, Any]:
    merged = merge_meshes(meshes, weld=weld)
    vertices: list[Vec] = merged["vertices"]
    triangles = merged["triangles"]
    # Drop vertices no surviving triangle references so OBJ output and counts stay honest.
    used = sorted({index for triangle in triangles for index in triangle})
    if len(used) != len(vertices):
        remap = {old: new for new, old in enumerate(used)}
        vertices = [vertices[old] for old in used]
        triangles = [(remap[a], remap[b], remap[c]) for a, b, c in triangles]
    manifold = analyze_manifold(vertices, triangles)
    scale = 1.0
    if longest_edge_mm is not None:
        vertices, scale = scale_to_longest_edge(vertices, longest_edge_mm)
    low, high = bounds(vertices)
    report = {
        "sourceMeshCount": merged["sourceMeshCount"],
        "sourceTriangleCount": merged["sourceTriangleCount"],
        "degenerateTrianglesDropped": merged["degenerateTrianglesDropped"],
        "vertexCount": len(vertices),
        "triangleCount": len(triangles),
        "weld": weld,
        "scaleFactor": scale,
        "units": "mm" if longest_edge_mm is not None else "source",
        "bounds": {"min": list(low), "max": list(high), "size": [high[i] - low[i] for i in range(3)]},
        **manifold,
    }
    report["volume"] = sum(shell["signedVolume"] for shell in manifold["shells"]) * scale ** 3
    for shell in report["shells"]:
        shell["signedVolume"] *= scale ** 3
    return {"vertices": vertices, "triangles": triangles, "report": report}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bake meshes.json into a printable STL/OBJ with a manifold gate")
    parser.add_argument("meshes", type=Path, help="world-space meshes.json (export_mesh_geometry.mjs format)")
    parser.add_argument("--out", type=Path, required=True, help="output .stl or .obj")
    parser.add_argument("--format", choices=FORMATS, help="defaults to the --out suffix")
    parser.add_argument("--longest-edge-mm", type=float, help="scale so the longest bounding-box edge is this many mm")
    parser.add_argument("--weld", type=float, default=DEFAULT_WELD, help=f"vertex weld distance (default {DEFAULT_WELD})")
    parser.add_argument("--allow-open", action="store_true", help="write the file even when the mesh is not watertight")
    parser.add_argument("--report", type=Path, help="write the JSON report here")
    parser.add_argument("--json", action="store_true", help="print the JSON report on stdout")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    fmt = args.format or args.out.suffix.lower().lstrip(".")
    if fmt not in FORMATS:
        parser.error(f"cannot infer format from {args.out.name!r}; pass --format stl|obj")
    if args.out.exists() and not args.force:
        parser.error(f"{args.out} already exists; use --force to overwrite")
    try:
        payload = json.loads(args.meshes.read_text(encoding="utf-8"))
        result = build_export(load_meshes(payload), weld=args.weld, longest_edge_mm=args.longest_edge_mm)
    except (OSError, json.JSONDecodeError, PrintExportError) as error:
        print(f"print export error: {error}", file=sys.stderr)
        return 2
    report = result["report"]
    printable = report["watertight"] and report["insideOutShellCount"] == 0
    written = printable or args.allow_open
    report["printable"] = printable
    report["written"] = written
    report["output"] = str(args.out) if written else None
    report["format"] = fmt
    if written:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        writer = write_stl if fmt == "stl" else write_obj
        writer(args.out, result["vertices"], result["triangles"], name=args.meshes.stem)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        size = " x ".join(f"{value:.3f}" for value in report["bounds"]["size"])
        verdict = "PRINTABLE" if printable else "NOT WATERTIGHT"
        print(f"{verdict}: {report['triangleCount']} triangles, {report['shellCount']} shell(s), "
              f"size {size} {report['units']}")
        print(f"  boundary edges={report['boundaryEdgeCount']} non-manifold edges={report['nonManifoldEdgeCount']} "
              f"misoriented edges={report['misorientedEdgeCount']} inside-out shells={report['insideOutShellCount']} "
              f"degenerate dropped={report['degenerateTrianglesDropped']}")
        print(f"  wrote {args.out}" if written else "  refused to write (pass --allow-open to export anyway)")
    return 0 if printable else 1


if __name__ == "__main__":
    raise SystemExit(main())
