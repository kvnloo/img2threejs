# Vehicle plan-taper evidence (experimental)

An opt-in, Python-stdlib-only geometry gate for the missing **plan-view vehicle-body vocabulary** in [upstream issue #38](https://github.com/img2threejs/img2threejs/issues/38) (reported by `djmmts`). It flags the toy-like constant-width/stadium-shaped body problem even when all wheels, louvers, lamps, and other specified parts exist.

The gate **does not** invent plan geometry or infer the reference profile from a single photograph. A human/agent must measure a trusted top-down orthographic reference before claiming a pass. This checks the reconstructed body mesh, not rendered pixels. Multi-part bodies need an explicitly prepared single geometry mesh; the script will not arbitrarily combine a body with fenders, windows or props.

## Inputs

- `meshes.json`: world-space triangle mesh evidence (e.g. from the separately reviewed browser exporter); requires `"coordinateSpace": "world"`, exactly one mesh named `body`, and an explicit Boolean `"incomplete": false`. Missing, null, stringified or truthy completeness values fail closed. Reported `skippedMeshes`/`skipped` entries must be lists of explicitly `hidden` or `filtered` geometry; active/unknown omissions block the gate even if the exporter claims complete. The consumer never assumes a partial export was complete.
- `sections.json`: reference measurements at three or more increasing longitudinal world-space X positions, with lateral widths along Z. The `reference.source` is an evidence label, not independently verified image content.

```json
{
  "schemaVersion": 1,
  "axis": "x", "lateralAxis": "z",
  "reference": {"kind": "measured-top-view", "source": "top-reference.png"},
  "maxNormalizedWidthError": 0.08,
  "maxTaperLoss": 0.12,
  "stations": [
    {"id": "nose", "x": -2, "referenceWidth": 0.6},
    {"id": "front-fender", "x": -1, "referenceWidth": 1.0},
    {"id": "door", "x": 0, "referenceWidth": 0.8},
    {"id": "rear-hip", "x": 1, "referenceWidth": 1.0},
    {"id": "tail", "x": 2, "referenceWidth": 0.5}
  ]
}
```

```bash
python3 integrations/vehicle_form/plan_taper.py \
  --geometry meshes.json --sections sections.json --mesh body --json
python3 -m unittest forge.tests.test_vehicle_plan_taper
```

World X coordinates must already correspond across the model and reference table; all geometry comes from actual triangle/plane intersections, not the nearest vertex. Finite input coordinates do not guarantee finite *derived* widths or longitudinal spans (subtractions can overflow binary64). The gate rejects non-finite derived measurements rather than normalizing `inf/inf` into NaN and accidentally passing a tolerance comparison. Zero-area/collinear triangles are ignored (reported as `degenerateTrianglesIgnored`) because lines can produce arbitrary widths without contributing a real surface; if the selected body has no nondegenerate triangles, the gate refuses the evidence. **Surface coverage guard:** Width extrema alone are insufficient. Two disconnected
longitudinal rails at opposite Z edges can match every reference width while
leaving most of the body absent. The gate now intersects actual nondegenerate
triangles with each longitudinal station plane, merges their lateral Z
intervals and requires at least **90% surface-backed lateral coverage** at
every measured station. Missing support is an input/evidence error (exit 2),
not a passing shape score. Each passing station records
`lateralCoverageFraction` for inspection. The synthetic regression proves
that exact-width side-only rails fail while the fully connected prism passes.

This measures **projected section coverage**, not watertightness, thickness,
surface orientation, connectivity away from the sampled planes, or actual
visual fidelity. A single crossing sheet can still cover the full Z span;
additional mesh/silhouette checks remain necessary.

Widths are normalized to their respective maximum, so this is a **shape** gate, not a real-world dimension or wheelbase accuracy check. It does not measure silhouette height/tumblehome, reflectance, clearance, volume, or unseen body panels.

**Exit codes:** `0` accepted shape, `1` measured shape mismatch, `2` unusable or unmeasurable evidence. A partial/empty export never counts as a clean model. Do not wire this into the generic core pipeline without a domain integration and reference-image measurement policy.

## Reproducible browser pixel-to-mesh A/B (synthetic)

A separate, opt-in CI job exercises **actual Three.js/WebGL pixels**, rather than only
feeding hand-constructed triangle arrays to the gate:

1. Render a procedurally assembled vehicle reference from a locked orthographic top camera.
2. Measure nose, front-fender, door, rear-hip and tail widths **from the PNG framebuffer**, recording the screenshot SHA-256 and each sampled pixel column.
3. Render two candidate bodies: the original varying-width profile and an intentionally wrong constant-width/stadium profile.
4. Export each candidate through the *pinned downstream* real-browser mesh exporter from [fork PR #35](https://github.com/kvnloo/img2threejs/pull/35), excluding studio geometry via an explicit model root.
5. Require the measured pixel profile to accept the matching exported triangles and reject the stadium geometry. Fail closed on a partial exporter retry and record its diagnostic separately.

The GitHub Actions workflow is `.github/workflows/vehicle-plan-ab-smoke.yml`.
It uses `node --test integrations/vehicle_form/vehicle_reference_pixels.test.mjs` plus
`node integrations/vehicle_form/vehicle_browser_ab_smoke.mjs`, with optional Playwright
and Three.js installed into a temporary directory, not the generic core. The workflow
pins an exact exporter commit and retains rendered reference/candidate screenshots,
`vehicle-ab-comparison.png`, input sections, mesh receipts and both gate reports.

**Scope:** This is synthetic-browser integration and geometry/pixel consistency evidence,
not a photograph of the 1960s Ferrari from the original issue, not recovered 3D depth,
and not a real-world automotive reconstruction accuracy result. An independently measured
reference photograph and reproducible before/after Ferrari rebuild are still required
before claiming that real-world form fidelity improved.
