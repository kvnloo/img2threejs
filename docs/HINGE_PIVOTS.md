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
- `restAngleDeg` is optional (defaults to 0), a finite angle around the directed
  `axisStart -> axisEnd` axis (right-hand rule), in degrees.
- An absent `hinge` emits the original hierarchy unchanged. Malformed,
  degenerate, or non-finite hinge declarations fail spec validation.

The generator inserts a pivot at `axisStart`, aligns a frame to the axis,
rotates its Y-axis by `restAngleDeg`, then applies the inverse frame and the
component's original translation. At zero degrees this composes to the
original unhinged transform. A separate offset group leaves the exposed
`nodes[id].position` equal to the authored position. Parent-child relationships,
mesh-local sockets, and authored rotation stay on the component node.

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

The standard Python tests assert generated hierarchy, validator failures,
nested parenting, endpoint-derived attachment compatibility, and unchanged
legacy output.

### Actual browser verification

Run the separate [hinge-runtime workflow](../.github/workflows/hinge-runtime.yml)
or reproduce its test locally with Node 22, Python 3.10+, and Chromium:

```sh
npm install --no-save --no-package-lock --ignore-scripts \
  three@0.180.0 @types/three@0.180.0 \
  typescript@5.9.3 esbuild@0.25.12 playwright@1.56.1
npx --no-install playwright install --with-deps chromium
HINGE_SCREENSHOTS=/tmp/hinge-screenshots node forge/tests/hinge_runtime.mjs
```

The fixture uses the real Python generator, typechecks its emitted TypeScript,
bundles it into Chromium, and asserts world-space transforms for an off-center
hinge, two nested hinges, and a diagonal axis. It verifies both shared crease
edges remain coincident at 5-degree intervals throughout the 0–90 degree lid
sweep. Three actual WebGL renders (0, 45, and 90 degrees) are uploaded to
the workflow's `hinge-swept-views` artifact for human inspection.

This proves browser execution and *fixture* hinge articulation, not
reference-image reconstruction fidelity or collision-free folding on arbitrary
subjects. Hinge joints are animation transforms, not physics constraints or
inverse-kinematics solvers. Hinges on bone-bound character/hybrid components
are rejected because skinning reparents their meshes outside the hinge
hierarchy. No external mesh, art asset, or ML model is downloaded.
