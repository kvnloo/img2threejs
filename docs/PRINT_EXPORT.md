# print_export.py — image to printable model

Maker-facing documentation for `forge/stage3_build/print_export.py`. It closes issue #3:
turn the reconstructed procedural Three.js model into a geometry file a 3D-print slicer
can accept, and refuse silently-broken output.

## Purpose

`print_export.py` bakes the exported world-space meshes into a single **STL** or **OBJ**
file, gated by a manifold check. It fails closed: a model with boundary edges,
non-manifold edges, inconsistent winding, inside-out shells, or zero-volume closed shells is **not written** unless
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

**Input completeness:** a browser receipt declaring `schemaVersion`,
`coordinateSpace`, `skippedMeshes` or `skipped` must also explicitly declare
`"incomplete": false` as a JSON Boolean; omission or a truthy/stringified
value is not proof that every live mesh was captured. The supported receipt
schema is integer `"schemaVersion": 1` and its coordinates must be
`"world"`. `--allow-open` only permits intentionally open **captured**
geometry; it never overrides missing/skipped live meshes. Legacy raw arrays
and simple mesh containers without exporter metadata remain supported.
Only intentionally `hidden` and `filtered` skip entries are accepted;
active or malformed skips fail closed even if completeness is declared false.

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
- `shellCount`, `insideOutShellCount`, `zeroVolumeShellCount`, `shells[]` — per shell: `triangleCount`,
  `closed`, `signedVolume`, `insideOut` (negative volume = flipped normals), `zeroVolume` (closed but negligible enclosed volume)
- `volume` — sum of shell signed volumes, scaled
- `printable`, `written`, `output` (`null` when refused), `format`

## Limits (read this before slicing)

- **No boolean union.** Overlapping parts are *not* merged; internal faces stay in the
  file. A procedural `THREE.Group` usually overlaps (embedded attachments), but most
  slicers union overlapping closed shells themselves — the report's `shellCount` and
  `shells[]` tell you what your slicer will receive.
- **Zero-volume closed shells are refused.** Back-to-back coplanar triangles can pass every edge-use and connected-fan check while enclosing no solid. The per-shell extent-normalized volume gate refuses these. This does not enforce a minimum printable wall thickness.
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
tiny source geometry for printing. The exporter also normalizes the source
filename into a bounded, portable single-line object name for the OBJ `o`
record and binary STL header. Control characters (including newlines) can
never insert additional OBJ vertex/face commands through a filename.

- **STL float32 precision.** Binary STL stores every coordinate as a 32-bit float.
  Extremely tiny triangles or large world offsets can round different vertices
  to identical coordinates, producing a degenerate print even when the original
  Python mesh is topologically closed. Before writing STL, the exporter checks
  each triangle after float32 conversion and refuses any collapse (exit code 2).
  Even when every triangle retains a positive area, distinct vertices
  from separate closed shells can round to identical float32 coordinates:
  for example, a small gap near a world X coordinate of 1001 may vanish,
  creating coincident faces in the slicer. The exporter also refuses **new
  vertex collisions after float32 rounding**, before publishing any STL.
  A valid source triangle can even reverse its winding during float32
  rounding while staying nondegenerate. Such faces are refused, and for
  accepted triangles the written STL facet normals are recomputed from
  the **stored** quantized vertices, not mismatched source-space positions.
  For very small meshes, set `--weld` below the smallest meaningful
  source-space feature **and** use `--longest-edge-mm` to rescale them; the
  weld occurs before rescaling. For distant world origins, recenter the source
  geometry before exporting. OBJ writes 17 significant decimal digits, so it
  can retain double-precision detail that binary STL cannot.


## Independent OpenSCAD STL round-trip

`python3 scripts/print_export_openscad_smoke.py` requires an installed
`openscad` CLI. It writes an original world-space box through
`print_export.py --longest-edge-mm 60`, imports the generated **binary STL**
in a separate OpenSCAD process, exports ASCII STL, and independently
measures its triangle count, dimensions and oriented volume from the
OpenSCAD-produced vertices. This catches some serializer/importer
interoperability errors without relying on the Python exporter report.

[Verified CI run](https://github.com/kvnloo/img2threejs/actions/runs/39272274156)
used OpenSCAD 2021.01: **12 triangles, 20×40×60 mm, 48,000 mm³**.
It does **not** independently validate arbitrary self-intersections,
print supports, slicer G-code, or a reconstructed photograph.

## Optional end-to-end browser and slicer verification

The downstream PR includes the print-browser-integration GitHub workflow to
verify the **actual cross-repository boundary**, not just the serializer.
It pins the browser mesh-exporter candidate from fork PR #35 to a reviewed
commit, captures real headless Chromium/Three.js geometry from both static
instances and an actual stage3-generated procedural factory, then:

1. Converts those captured world-space meshes to STL and OBJ in millimeters.
2. Independently re-imports both formats with an isolated Trimesh library:
   tests watertightness, winding, dimensions, shell count, and volume parity.
   Trimesh is an optional integration-test dependency, **not** a forge dependency.
3. Rejects a real incomplete browser receipt, false local-coordinate receipt,
   and conflicting incomplete:false/active-skipped receipt, even with
   --allow-open --force, while preserving any prior STL file.
4. Uses the Ubuntu Slic3r 1.3 command-line slicer to generate actual G-code
   from the browser-derived instanced-box STL and checks extrusion moves and
   multiple layer heights. The G-code is test evidence, not printer instructions.

Verified 2026-10-19:
https://github.com/kvnloo/img2threejs/actions/runs/39270922479
The controlled slicer fixture produced 5,149 extrusion moves across
68 commanded Z heights. Artifacts include browser screenshots, source
geometry, STL/OBJ, independently parsed import receipts, and G-code.

**Limits:** These are controlled original procedural fixtures. They are NOT
proof of likeness to a supplied photograph or printable completion of the
loot-chest demo. Actual print safety, wall thickness, supports, calibration
and physical output must be independently checked for the chosen printer.

### Stable geometric scaling

Triangle area uses a stable vector norm so very small, but finite, input
features are not silently discarded before the requested physical scaling.
Signed shell volumes are measured on the final scaled geometry rather than
using a potentially overflowing intermediate `scaleFactor ** 3`. A
non-finite factor, coordinate or volume is a hard input error; none produces a
printable artifact. Input-vertex welding is still performed before scaling,
so set `--weld` in the source coordinate units.

### Atomic report receipts

The optional `--report` JSON is written to a temporary file in its destination
directory, flushed and atomically replaced only after serialization succeeds.
A failed report write returns exit status 2 and preserves the previous report,
never a truncated success-looking receipt. The already-committed STL/OBJ may
still exist; its validity is separate from success of the report receipt.
A report destination that is a directory is rejected before publishing geometry.
