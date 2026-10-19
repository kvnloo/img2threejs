# Off-center hinge pivots (experimental)

Refs [img2threejs/img2threejs#118](https://github.com/img2threejs/img2threejs/issues/118) by [mariusargint](https://github.com/mariusargint).

This opt-in extension makes a component rotate about an **edge** rather than its
center. Typical uses are lids, folding cartons, doors, books, and articulated
hard-surface panels. It changes no existing specs or meshes.

## Spec

Add an optional `hinge` field to a component:

```json
{
  "id": "lid",
  "parent": "base",
  "primitive": "box",
  "transform": {
    "position": [0.5, 0.0, 0.0],
    "rotation": [0, 0, 0]
  },
  "hinge": {
    "axisStart": [0.0, 0.0, 0.0],
    "axisEnd": [0.0, 1.0, 0.0],
    "restAngleDeg": 0
  }
}
```

This is an excerpt of one `componentTree` entry; the complete spec still needs
its regular material, geometry, and review fields.

- `axisStart` and `axisEnd` are two distinct, finite 3D points **in the
  parent component node's frame** (or model-root frame for a root component).
- `transform.position` retains its old meaning: component center in the
  same parent frame. It is not reinterpreted as a hinge position.
- `restAngleDeg` is a finite angle around the directed
  `axisStart -> axisEnd` axis (right-hand rule), in degrees.
- An absent `hinge` emits the original hierarchy unchanged. Malformed,
  degenerate, or non-finite hinge declarations fail spec validation.

The generator inserts a pivot at `axisStart`, aligns a frame to the axis,
rotates its Y-axis by `restAngleDeg`, then applies the inverse frame and the
component's original translation. At zero degrees this composes to the
original unhinged transform. Parent-child relationships, mesh-local sockets,
and authored component rotation remain anchored to the component node.

## Animate

The factory exposes `root.userData.sculptRuntime.hinges` **only when a hinge
is present in the emitted pass**. Each entry is a `THREE.Group`, indexed by
component ID; its local Y rotation is the fold angle:

```ts
const runtime = root.userData.sculptRuntime as ProceduralModelRuntime;
runtime.hinges["lid"].rotation.y = THREE.MathUtils.degToRad(75);
```

Setting an absolute angle replaces `restAngleDeg`. Nested hinges can be
animated independently: the child hinge is parented beneath its component's
normal `nodes[parentId]` pivot and therefore follows the parent fold.

## Verification and limits

```sh
python3 -m unittest forge.tests.test_hinge_pivots
python3 -m unittest discover -s forge/tests -p 'test_*.py'
```

The automated tests assert generated hierarchy, validator failures, nested
parenting, endpoint-derived attachment compatibility, and legacy output.
The next acceptance gate is to capture a real Three.js browser render of a
hinged box/lid at 0, 45, and 90 degrees, plus a full swept-motion check for
interpenetration. These tests do **not** prove collision-free folding, image
fidelity, or WebGL rendering. Hinge joints are animation transforms, not a
physics constraint or inverse-kinematics solver. No external mesh, asset,
or ML download is involved.
