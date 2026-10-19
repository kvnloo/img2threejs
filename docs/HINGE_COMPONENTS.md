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
three groups between the parent and that pivot: an axis-alignment group,
a Y-rotation group, and an inverse-alignment group. At 0 degrees these
cancel, preserving the original component transform; at nonzero angles
the subtree swings about the declared edge. Children may declare their
own hinges, so fold chains are hierarchical.

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

Validation: `python3 -m unittest discover -s forge/tests -p 'test_*.py'`
and a separate TypeScript/Three.js showcase compile and visual screenshot
gate before any visual-fidelity or upstream completion claim.
