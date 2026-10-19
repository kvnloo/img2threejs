# Parent-local component hinges (experimental)

This optional ObjectSculptSpec extension addresses the folding-carton reproducer in
[img2threejs/img2threejs#118](https://github.com/img2threejs/img2threejs/issues/118)
reported by @mariusargint.

A component can declare an edge hinge without replacing its procedural geometry:

```json
{
  "id": "lid",
  "parent": "box",
  "level": "macro",
  "primitive": "box",
  "material": "base",
  "dimensions": {"width": 1, "height": 0.02, "depth": 1},
  "transform": {"position": [0.5, 1, 0], "rotation": [0, 0, 0]},
  "hinge": {
    "axisStart": [0, 1, 0],
    "axisEnd": [0, 1, 1],
    "restAngleDeg": 90
  }
}
```

Both `axisStart` and `axisEnd` are three finite coordinates **in the
parent component's local frame**, with a nonzero separation. The directed
axis establishes the sign of positive rotation (right-hand rule).
`restAngleDeg` is optional, defaults to 0, and is specified in degrees.
Malformed and zero-length axes fail spec validation.

The generator retains the original component pivot in
`root.userData.sculptRuntime.nodes[id]`. For a hinged component it inserts
four groups between parent and pivot: axis-alignment, Y-rotation,
inverse-alignment, and translation offset. The offset keeps the exposed
`nodes[id].position` equal to the authored local position rather than
silently mutating it. At 0 degrees these transforms compose to the
unhinged pose; at nonzero angles the subtree swings about the declared
edge. Children may declare their own hinges, so fold chains are hierarchical.

To animate a fold after creating the model:

```js
const runtime = model.userData.sculptRuntime;
runtime.hinges["lid"].rotation.y = Math.PI / 2; // radians at runtime
```

The `hinges` map exists only on factories containing hinges in the emitted
pass. Unhinged specs retain their previous emitted hierarchy and runtime
shape. Hinges do not run collision or swept self-intersection checks: a
valid final angle may still drive a panel through its neighbor. Character
skin/bone deformation and visual fidelity are not established by the
generator-only tests.

Validation:
```sh
python3 -m unittest discover -s forge/tests -p 'test_*.py'
npm install --no-save --no-package-lock --ignore-scripts \
  three@0.180.0 @types/three@0.180.0 \
  typescript@5.9.3 esbuild@0.25.12 playwright@1.56.1
npx --no-install playwright install --with-deps chromium
HINGE_SCREENSHOTS=/tmp/hinge-screenshots node forge/tests/hinge_runtime.mjs
```

An [opt-in downstream WebGL acceptance harness](https://github.com/kvnloo/img2threejs/tree/study/hinge-real-photo-ab-20261019/forge/tests)
compiles the actual generated TypeScript, verifies nested parent-frame
joint world transforms and lid/flap crease continuity across a 0–90
degree sweep, and captures Chromium views at 0/45/90 degrees.
[Passing Chromium/TypeScript evidence](https://github.com/kvnloo/img2threejs/actions/runs/39214481055).
The Python-only core remains dependency-free; browser tooling and
downloaded reference images stay outside this proposed upstream patch.

This proves fixture articulation, not reference-image reconstruction fidelity
or collision-free motion for arbitrary subjects. Bone-bound components in
character/hybrid skinning cannot declare hinges because the skinned mesh is
reparented outside its pivot; unsupported hinge keys fail validation.
