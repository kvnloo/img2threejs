# print_export.py — image to printable model

Maker-facing documentation for `forge/stage3_build/print_export.py`. It closes issue #3:
turn the reconstructed procedural Three.js model into a geometry file a 3D-print slicer
can accept, and refuse silently-broken output.

## Purpose

`print_export.py` bakes the exported world-space meshes into a single **STL** or **OBJ**
file, gated by a manifold check. It fails closed: a model with boundary edges,
non-manifold edges, inconsistent winding, or inside-out shells is **not written** unless
you explicitly pass `--allow-open`. A slicer never silently receives a broken model.

## Pipeline

1. Produce world-space `meshes.json` from the running model: a list of
   `{"name", "vertices": [[x, y, z], ...], "indices": [...]}` objects with every vertex
   already multiplied by the mesh's `matrixWorld` (the same input
   `forge/stage4_review/self_intersection.py` reads). `SKILL.md` names
   `runtime/scripts/export_mesh_geometry.mjs` as the producer, but that script is not yet
   shipped in this repository (#90); until it is, any traversal that calls
   `updateMatrixWorld(true)` and applies `matrixWorld` to each `position` attribute works.

2. Bake it into a printable file:

   ```
   python3 forge/stage3_build/print_export.py meshes.json \
       --out model.stl --longest-edge-mm 80 --report print-report.json
   ```

What the exporter does: merges every mesh into one triangle soup, welds coincident
vertices (`--weld`), drops zero-area/duplicate-index triangles, checks every merged
shell is closed, two-manifold, and consistently wound, optionally rescales so the
longest bounding-box edge equals `--longest-edge-mm`, then writes binary STL (or OBJ)
plus a JSON report.

## CLI reference (exactly as in `build_parser`)

| Argument | Meaning |
| --- | --- |
| `meshes` (positional) | world-space `meshes.json` (the `export_mesh_geometry.mjs` format) |
| `--out` (required) | output file; extension must be `.stl` or `.obj` (or pass `--format`) |
| `--format {stl,obj}` | force output format; defaults to the `--out` suffix |
| `--longest-edge-mm` | scale the model so its longest bounding-box edge is this many mm |
| `--weld` | vertex weld distance; default `1e-6` |
| `--allow-open` | write the file even when the mesh is not watertight |
| `--report` | write the JSON report to this path |
| `--json` | print the JSON report on stdout instead of the human summary |
| `--force` | overwrite an existing output file |

## Exit codes

- `0` — printable: watertight, no inside-out shells, file written.
- `1` — **not watertight**: file refused unless `--allow-open` was passed (with it the
  file is written but the exit code is still `1`, so scripts notice).
- `2` — input error: missing/unreadable/malformed JSON, invalid mesh data, no
  recognizable format, or `--out` exists without `--force`.

## Report fields (`--report` / `--json`)

- `sourceMeshCount`, `sourceTriangleCount`, `degenerateTrianglesDropped`
- `vertexCount`, `triangleCount` — after weld and degenerate-triangle removal
- `weld`, `scaleFactor`, `units` (`"mm"` with `--longest-edge-mm`, else `"source"`)
- `bounds` — `{min, max, size}` of the output geometry
- `watertight` — true when boundary, non-manifold, and misoriented edge counts are 0
- `boundaryEdgeCount`, `nonManifoldEdgeCount`, `misorientedEdgeCount`
- `boundaryEdgeSample`, `nonManifoldEdgeSample` — up to 8 problem edges each
- `shellCount`, `insideOutShellCount`, `shells[]` — per shell: `triangleCount`,
  `closed`, `signedVolume`, `insideOut` (negative volume = flipped normals)
- `volume` — sum of shell signed volumes, scaled
- `printable`, `written`, `output` (`null` when refused), `format`

## Limits (read this before slicing)

- **No boolean union.** Overlapping parts are *not* merged; internal faces stay in the
  file. A procedural `THREE.Group` usually overlaps (embedded attachments), but most
  slicers union overlapping closed shells themselves — the report's `shellCount` and
  `shells[]` tell you what your slicer will receive.
- **No wall-thickness analysis.** The manifold gate says nothing about whether walls
  are thick enough to print or hollow outlines; check in your slicer.
- **Hidden faces are approximated.** With single-image input, reconstructed hidden
  surfaces (the far side of the object) are estimates, not measurements.
- **Open shells are refused.** Planes, thin sheets, and any non-closed shell have
  boundary edges and fail the gate — intentionally. Pass `--allow-open` to export
  them anyway, but such geometry is not watertight and slicers should be trusted
  accordingly.
