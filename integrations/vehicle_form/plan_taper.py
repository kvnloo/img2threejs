#!/usr/bin/env python3
"""Compare a vehicle body's measured plan-view widths against top-view evidence.

This is an optional vehicle-domain experiment. It does not infer unseen 3D geometry
from a photograph, and it never substitutes a render or a heuristic for the user's
explicit, measured top-view station table. Python 3.10+ standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


class PlanTaperInputError(ValueError):
    """The inputs cannot support a geometric verdict."""


# A width supported only by disconnected edge rails is not a body silhouette.
# This intentionally does not certify mesh volume or watertightness.
MIN_LATERAL_SPAN_COVERAGE = 0.90


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanTaperInputError(f"{label} must be finite and numeric")
    try:
        val = float(value)
    except (OverflowError, ValueError) as exc:
        raise PlanTaperInputError(f"{label} must be finite and numeric") from exc
    if not math.isfinite(val):
        raise PlanTaperInputError(f"{label} must be finite and numeric")
    if positive and val <= 0:
        raise PlanTaperInputError(f"{label} must be positive")
    return val


def _mesh_from_export(payload: Any, name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PlanTaperInputError("geometry evidence must be an exporter JSON object")
    # A missing or non-Boolean completeness flag is not a clean export.
    # In particular, "false", 0, and null must never masquerade as False.
    if payload.get("incomplete") is not False:
        raise PlanTaperInputError("partial or unverified mesh export cannot support a plan-taper verdict")
    if payload.get("coordinateSpace") != "world":
        raise PlanTaperInputError("geometry evidence must declare coordinateSpace: world")
    # An exporter may claim completeness while reporting active, skipped meshes.
    # Such a receipt cannot certify the selected body or assembly as fully sampled.
    for field in ("skippedMeshes", "skipped"):
        if field not in payload:
            continue
        skips = payload[field]
        if not isinstance(skips, list):
            raise PlanTaperInputError(f"invalid {field}: expected a list")
        if any(not isinstance(entry, dict) or entry.get("reason") not in {"hidden", "filtered"}
               for entry in skips):
            raise PlanTaperInputError(
                f"partial or unverified mesh export: {field} omits active or unknown geometry"
            )
    meshes = payload.get("meshes")
    if not isinstance(meshes, list):
        raise PlanTaperInputError("geometry evidence needs a meshes array")
    selected = [m for m in meshes if isinstance(m, dict) and m.get("name") == name]
    if len(selected) != 1:
        raise PlanTaperInputError(f"expected exactly one mesh named {name!r}, found {len(selected)}")
    return selected[0]


def _triangles(mesh: dict[str, Any]) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], int]:
    raw_vertices = mesh.get("vertices")
    if not isinstance(raw_vertices, list) or len(raw_vertices) < 3:
        raise PlanTaperInputError("selected mesh has fewer than 3 vertices")
    if len(raw_vertices) > 500_000:
        raise PlanTaperInputError("selected mesh exceeds 500000 vertices")
    vertices = []
    for i, vertex in enumerate(raw_vertices):
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 3:
            raise PlanTaperInputError(f"vertices[{i}] must be a 3D coordinate")
        vertices.append(tuple(_number(n, f"vertices[{i}]") for n in vertex))

    raw_indices = mesh.get("indices")
    if not isinstance(raw_indices, list) or not raw_indices:
        raise PlanTaperInputError("selected mesh needs triangle indices")
    if isinstance(raw_indices[0], (tuple, list)):
        groups = raw_indices
    else:
        if len(raw_indices) % 3:
            raise PlanTaperInputError("flat triangle indices must be divisible by 3")
        groups = [raw_indices[i:i + 3] for i in range(0, len(raw_indices), 3)]
    if len(groups) > 250_000:
        raise PlanTaperInputError("selected mesh exceeds 250000 triangles")
    triangles = []
    ignored_degenerate = 0
    for i, group in enumerate(groups):
        if not isinstance(group, (tuple, list)) or len(group) != 3:
            raise PlanTaperInputError(f"triangle {i} needs exactly 3 indices")
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 or v >= len(vertices) for v in group):
            raise PlanTaperInputError(f"triangle {i} has an invalid vertex index")
        a, b, c = (vertices[v] for v in group)
        ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        if not all(math.isfinite(value) for value in cross):
            raise PlanTaperInputError(f"triangle {i} has an unmeasurable area")
        if not any(cross):
            # A line or point at a station can have wide min/max Z without
            # enclosing any vehicle body surface. Do not count it as evidence.
            ignored_degenerate += 1
            continue
        triangles.append(tuple(group))
    if not triangles:
        raise PlanTaperInputError("selected mesh has no nondegenerate surface triangles")
    return vertices, triangles, ignored_degenerate


def _validate_sections(payload: Any) -> tuple[list[dict[str, Any]], float, float, float | None]:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise PlanTaperInputError("section table needs schemaVersion: 1")
    if payload.get("axis") != "x" or payload.get("lateralAxis") != "z":
        raise PlanTaperInputError("v1 supports longitudinal x and lateral z in world space only")
    reference = payload.get("reference")
    if not isinstance(reference, dict) or reference.get("kind") != "measured-top-view" or not isinstance(reference.get("source"), str) or not reference["source"].strip():
        raise PlanTaperInputError("reference must identify its measured-top-view source")
    raw_stations = payload.get("stations")
    if not isinstance(raw_stations, list) or len(raw_stations) < 3:
        raise PlanTaperInputError("at least three reference stations are required")
    if len(raw_stations) > 32:
        raise PlanTaperInputError("at most 32 reference stations are supported")
    stations = []
    ids = set()
    center_enabled = any(isinstance(row, dict) and "referenceCenterZ" in row for row in raw_stations)
    if center_enabled and not all(isinstance(row, dict) and "referenceCenterZ" in row for row in raw_stations):
        raise PlanTaperInputError("referenceCenterZ must be measured at every station or omitted entirely")
    for i, row in enumerate(raw_stations):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip():
            raise PlanTaperInputError(f"stations[{i}] needs a nonempty id")
        if row["id"] in ids:
            raise PlanTaperInputError(f"duplicate station id: {row['id']}")
        ids.add(row["id"])
        x = _number(row.get("x"), f"stations[{i}].x")
        width = _number(row.get("referenceWidth"), f"stations[{i}].referenceWidth", positive=True)
        if stations and x <= stations[-1]["x"]:
            raise PlanTaperInputError("stations must be ordered by strictly increasing x")
        station = {"id": row["id"], "x": x, "referenceWidth": width}
        if center_enabled:
            station["referenceCenterZ"] = _number(
                row["referenceCenterZ"], f"stations[{i}].referenceCenterZ"
            )
        stations.append(station)
    width_tolerance = _number(payload.get("maxNormalizedWidthError", 0.08), "maxNormalizedWidthError")
    taper_tolerance = _number(payload.get("maxTaperLoss", 0.12), "maxTaperLoss")
    if not 0 <= width_tolerance < 1 or not 0 <= taper_tolerance < 1:
        raise PlanTaperInputError("tolerances must be in [0, 1)")
    center_tolerance = None
    if center_enabled:
        center_tolerance = _number(
            payload.get("maxNormalizedCenterError", 0.08), "maxNormalizedCenterError"
        )
        if not 0 <= center_tolerance < 1:
            raise PlanTaperInputError("maxNormalizedCenterError must be in [0, 1)")
    elif "maxNormalizedCenterError" in payload:
        raise PlanTaperInputError("maxNormalizedCenterError requires referenceCenterZ at every station")
    return stations, width_tolerance, taper_tolerance, center_tolerance


def _section_width(
    vertices: list[tuple[float, float, float]],
    triangles: list[tuple[int, int, int]],
    x: float,
    epsilon: float,
) -> tuple[float, float, int, float]:
    """Measure section width, centerline, and the fraction backed by surface.

    A pair of thin, disconnected side rails can have the correct min/max Z at
    every station and still be missing the entire body between them. Require
    actual triangle-plane segments to cover the width, not just two extrema.
    """
    z_hits: list[float] = []
    intervals: list[tuple[float, float]] = []
    for a, b, c in triangles:
        tri = (vertices[a], vertices[b], vertices[c])
        if x < min(p[0] for p in tri) - epsilon or x > max(p[0] for p in tri) + epsilon:
            continue
        hits: list[float] = []
        for first, second in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            dx = second[0] - first[0]
            if abs(dx) <= epsilon:
                if abs(x - first[0]) <= epsilon:
                    hits.extend((first[2], second[2]))
            else:
                fraction = (x - first[0]) / dx
                if -1e-12 <= fraction <= 1 + 1e-12:
                    fraction = max(0.0, min(1.0, fraction))
                    hits.append(first[2] + fraction * (second[2] - first[2]))
        if hits:
            if not all(math.isfinite(hit) for hit in hits):
                raise PlanTaperInputError(f"non-finite lateral section intersection at x={x:g}")
            z_hits.extend(hits)
            if len(hits) >= 2:
                intervals.append((min(hits), max(hits)))
    if len(z_hits) < 2:
        raise PlanTaperInputError(f"no measurable cross-body section at x={x:g}")
    width = max(z_hits) - min(z_hits)
    if not math.isfinite(width):
        raise PlanTaperInputError(f"non-finite lateral section width at x={x:g}")
    if width <= epsilon:
        raise PlanTaperInputError(f"no measurable cross-body section at x={x:g}")
    # Use the minimum plus half the width rather than (min + max)/2,
    # which can overflow for large positive but finite world coordinates.
    center = min(z_hits) + width / 2
    if not math.isfinite(center):
        raise PlanTaperInputError(f"non-finite lateral section center at x={x:g}")

    if not intervals:
        raise PlanTaperInputError(f"no surface-backed lateral span at x={x:g}")
    intervals.sort()
    begin, end = intervals[0]
    covered_parts = []
    for left, right in intervals[1:]:
        if left > end + epsilon:
            covered_parts.append(end - begin)
            begin, end = left, right
        else:
            end = max(end, right)
    covered_parts.append(end - begin)
    coverage = math.fsum(covered_parts) / width
    if not math.isfinite(coverage):
        raise PlanTaperInputError(f"non-finite lateral coverage at x={x:g}")
    coverage = max(0.0, min(1.0, coverage))
    if coverage + 1e-12 < MIN_LATERAL_SPAN_COVERAGE:
        raise PlanTaperInputError(
            f"insufficient surface-backed lateral coverage at x={x:g}: "
            f"{coverage:.3f} < {MIN_LATERAL_SPAN_COVERAGE:.3f}"
        )
    return width, center, len(z_hits), coverage


def evaluate(geometry: Any, table: Any, *, mesh_name: str) -> dict[str, Any]:
    """Compare normalized width profiles; return honest geometry coverage and failures."""
    if not isinstance(mesh_name, str) or not mesh_name.strip():
        raise PlanTaperInputError("mesh_name must be nonempty")
    stations, width_tol, taper_tol, center_tol = _validate_sections(table)
    vertices, triangles, ignored_degenerate = _triangles(_mesh_from_export(geometry, mesh_name))
    xs = [vertex[0] for vertex in vertices]
    scale = max(xs) - min(xs)
    if not math.isfinite(scale):
        raise PlanTaperInputError("non-finite longitudinal extent from world-space vertices")
    if scale <= 0:
        raise PlanTaperInputError("selected mesh has no longitudinal extent")
    epsilon = max(1e-12, scale * 1e-9)
    measured = []
    for station in stations:
        width, center, intersections, coverage = _section_width(
            vertices, triangles, station["x"], epsilon
        )
        measured.append({
            **station, "measuredWidth": width, "measuredCenterZ": center,
            "intersectionCount": intersections, "lateralCoverageFraction": coverage
        })
    reference_max = max(s["referenceWidth"] for s in measured)
    measured_max = max(s["measuredWidth"] for s in measured)
    errors: list[str] = []
    for row in measured:
        row["normalizedReferenceWidth"] = row["referenceWidth"] / reference_max
        row["normalizedMeasuredWidth"] = row["measuredWidth"] / measured_max
        row["normalizedWidthError"] = abs(row["normalizedReferenceWidth"] - row["normalizedMeasuredWidth"])
        if row["normalizedWidthError"] > width_tol + 1e-12:
            errors.append(f"station {row['id']!r}: normalized width error {row['normalizedWidthError']:.3f} > {width_tol:.3f}")
        if center_tol is not None:
            displacement = row["measuredCenterZ"] - row["referenceCenterZ"]
            if not math.isfinite(displacement):
                raise PlanTaperInputError(f"non-finite lateral center offset at station {row['id']!r}")
            row["normalizedCenterError"] = abs(displacement) / reference_max
            if not math.isfinite(row["normalizedCenterError"]):
                raise PlanTaperInputError(
                    f"non-finite normalized lateral center error at station {row['id']!r}"
                )
            if row["normalizedCenterError"] > center_tol + 1e-12:
                errors.append(
                    f"station {row['id']!r}: normalized center error "
                    f"{row['normalizedCenterError']:.3f} > {center_tol:.3f}"
                )
    reference_taper = max(s["normalizedReferenceWidth"] for s in measured) - min(s["normalizedReferenceWidth"] for s in measured)
    measured_taper = max(s["normalizedMeasuredWidth"] for s in measured) - min(s["normalizedMeasuredWidth"] for s in measured)
    if reference_taper - measured_taper > taper_tol + 1e-12:
        errors.append(f"plan-view taper collapsed: reference range {reference_taper:.3f} vs measured {measured_taper:.3f} (max loss {taper_tol:.3f})")
    return {"passed": not errors, "mesh": mesh_name, "measuredStationCount": len(measured),
            "triangleCount": len(triangles), "degenerateTrianglesIgnored": ignored_degenerate,
            "referenceTaper": reference_taper,
            "measuredTaper": measured_taper, "maxNormalizedWidthError": width_tol,
            "maxTaperLoss": taper_tol, "maxNormalizedCenterError": center_tol,
            "centerlineCompared": center_tol is not None,
            "stations": measured, "failures": errors,
            "reference": table["reference"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, required=True, help="world-space exporter meshes.json")
    parser.add_argument("--sections", type=Path, required=True, help="measured top-view section table")
    parser.add_argument("--mesh", required=True, help="exact body mesh name in the exporter")
    parser.add_argument("--json", action="store_true", help="print machine-readable evidence")
    args = parser.parse_args(argv)
    try:
        geometry = json.loads(args.geometry.read_text(encoding="utf-8"))
        table = json.loads(args.sections.read_text(encoding="utf-8"))
        report = evaluate(geometry, table, mesh_name=args.mesh)
    except (OSError, ValueError, TypeError) as exc:
        print(f"plan-taper input error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"plan-taper: {'PASS' if report['passed'] else 'FAIL'} "
              f"({report['measuredStationCount']} stations, {report['triangleCount']} triangles)")
        for failure in report["failures"]:
            print(f"  {failure}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
