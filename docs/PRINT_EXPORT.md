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
shell is closed and consistently wound, and every welded vertex has one
connected face fan (no corner-touching/pinched shells). It optionally rescales so the
longest bounding-box edge equals `--longest-edge-mm`, then writes binary STL (or OBJ)
plus a JSON report. STL/OBJ bytes are first written to a temporary file in the
output directory, then atomically published: a write or float32 serialization
error leaves no truncated output and does not destroy an existing file, even
with `--force`.

**Input completeness:** if the browser mesh exporter declares
`"incomplete": true` or a coordinate space other than `"world"`, the
print exporter refuses the receipt. `--allow-open` only permits intentionally
open **captured** geometry; it never overrides missing/skipped live meshes.
Legacy inputs without receipt metadata remain supported.

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
- `2` — input/write error: missing/unreadable/malformed JSON, partial or
  non-world-space mesh receipt, invalid mesh data, serialization failure,
  unrecognized format, or `--out` exists without `--force`.

## Report fields (`--report` / `--json`)

- `sourceMeshCount`, `sourceTriangleCount`, `degenerateTrianglesDropped`
- `vertexCount`, `triangleCount` — after weld and degenerate-triangle removal
- `weld`, `scaleFactor`, `units` (`"mm"` with `--longest-edge-mm`, else `"source"`)
- `bounds` — `{min, max, size}` of the output geometry
- `watertight` — true when boundary, overused/misoriented edges, and pinched vertices are absent
- `boundaryEdgeCount`, `nonManifoldEdgeCount`, `misorientedEdgeCount`
- `nonManifoldVertexCount`, `nonManifoldVertexSample` — welded vertices with disconnected incident face fans (up to 8 indices)
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
- **Open or pinched shells are refused.** Planes and sheets fail on boundary edges.
  Two closed solids touching at just one welded vertex fail the vertex-manifold gate,
  even if every edge appears exactly twice. Disjoint closed solids remain allowed.
  Pass `--allow-open` to export unprintable topology deliberately, but the CLI still
  exits `1` and reports `printable: false`.

### Output safety

Use distinct resolved paths for source `meshes.json`, STL/OBJ output, and
optional JSON report. Overlapping paths, including relative/symlink aliases,
are rejected instead of overwriting a valid geometry artifact with report
JSON. OBJ vertices retain round-trip float precision to avoid rounding small
features to zero. STL stores float32; use `--longest-edge-mm` to scale unusually
tiny source geometry for printing.

- **STL float32 precision.** Binary STL stores every coordinate as a 32-bit float.
  Extremely tiny triangles or large world offsets can round different vertices
  to identical coordinates, producing a degenerate print even when the original
  Python mesh is topologically closed. Before writing STL, the exporter checks
  each triangle after float32 conversion and refuses any collapse (exit code 2).
  For very small meshes, set `--weld` below the smallest meaningful
  source-space feature **and** use `--longest-edge-mm` to rescale them; the
  weld occurs before rescaling. For distant world origins, recenter the source
  geometry before exporting. OBJ writes 17 significant decimal digits, so it
  can retain double-precision detail that binary STL cannot.
