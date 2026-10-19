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

World X coordinates must already correspond across the model and reference table; all geometry comes from actual triangle/plane intersections, not the nearest vertex. Widths are normalized to their respective maximum, so this is a **shape** gate, not a real-world dimension or wheelbase accuracy check. It does not measure silhouette height/tumblehome, reflectance, clearance, volume, or unseen body panels.

**Exit codes:** `0` accepted shape, `1` measured shape mismatch, `2` unusable or unmeasurable evidence. A partial/empty export never counts as a clean model. Do not wire this into the generic core pipeline without a domain integration and reference-image measurement policy.
