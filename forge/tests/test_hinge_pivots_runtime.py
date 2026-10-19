"""Execute emitted hinge factories against real Three.js, not just source strings.

The opt-in CI job supplies an isolated Node project through
IMG2THREEJS_SHOWCASE_ROOT. Core Python tests remain dependency-free.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "forge" / "tests"),
                str(ROOT / "forge" / "stage2_spec"),
                str(ROOT / "forge" / "stage3_build")]

from generate_threejs_factory import generate  # noqa: E402
from test_hierarchy_scale import compile_generated_module  # noqa: E402
from showcase_test_support import showcase_root  # noqa: E402
from validate_sculpt_spec import validate_spec  # noqa: E402


def fixture() -> dict:
    def part(identifier, parent, x, y, z, hinge=None):
        component = {
            "id": identifier, "name": identifier, "role": "panel",
            "level": "macro", "primitive": "box", "parent": parent,
            "material": "clay",
            "dimensions": {"width": 0.2, "height": 0.2, "depth": 0.2},
            "transform": {"position": [x, y, z], "rotation": [0, 0, 0]},
        }
        if hinge is not None:
            component["hinge"] = hinge
        return component

    return {
        "targetName": "Hinge Runtime Probe", "schemaVersion": "2.1",
        "suitability": "pass", "coordinateFrame": {}, "silhouette": {},
        "proceduralStrategy": [], "materials": [{"id": "clay"}],
        "componentTree": [
            part("body", None, 0, 0, 0),
            part("panel", "body", 1, 0, 0,
                 {"axisStart": [0, 0, 0], "axisEnd": [0, 1, 0]}),
            part("flap", "panel", 1, 0, 0,
                 {"axisStart": [0, 0, 0], "axisEnd": [0, 0, 1],
                  "restAngleDeg": 0}),
            part("slat", "body", 1, 0, 0,
                 {"axisStart": [0, 0, 0], "axisEnd": [0, 0, 1],
                  "restAngleDeg": 0}),
            part("blocker", "body", 0, 0, -1),
        ],
    }


PROBE = """
import * as THREE from 'three';
import { createHingeRuntimeProbeModel } from './build/hierarchy-scale.js';

const model = createHingeRuntimeProbeModel();
const rt = model.userData.sculptRuntime;
const pos = (id) => {
  model.updateMatrixWorld(true);
  return rt.nodes[id].getWorldPosition(new THREE.Vector3()).toArray();
};
const clean = () => {
  rt.hinges.panel.rotation.y = 0;
  rt.hinges.flap.rotation.y = 0;
  rt.hinges.slat.rotation.y = 0;
};
clean();
const rest = { panel: pos('panel'), flap: pos('flap') };
const authored = rt.nodes.panel.position.toArray();
rt.hinges.panel.rotation.y = Math.PI / 4;
const fortyFive = pos('panel');
rt.hinges.panel.rotation.y = Math.PI / 2;
const ninety = pos('panel');

clean();
rt.hinges.slat.rotation.y = Math.PI / 2;
const arbitraryAxis = pos('slat');

clean();
rt.hinges.panel.rotation.y = Math.PI / 2;
rt.hinges.flap.rotation.y = Math.PI / 2;
const nested = pos('flap');

const sweep = (direction) => {
  clean();
  const touches = [];
  for (let step = 0; step <= 6; step++) {
    rt.hinges.panel.rotation.y = direction * step * Math.PI / 6;
    model.updateMatrixWorld(true);
    const panel = new THREE.Box3().setFromObject(rt.meshes.panel);
    const blocker = new THREE.Box3().setFromObject(rt.meshes.blocker);
    touches.push(panel.intersectsBox(blocker));
  }
  return touches;
};

const positiveSweep = sweep(1);
const negativeSweep = sweep(-1);
console.log(JSON.stringify({
  rest, authored, fortyFive, ninety, arbitraryAxis, nested,
  positiveSweep, negativeSweep,
  hingeCount: Object.keys(rt.hinges).length,
  componentCount: Object.keys(rt.nodes).length,
}));
"""


class HingeThreeRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        host = showcase_root()
        spec = fixture()
        errors, _warnings = validate_spec(spec)
        if errors:
            raise RuntimeError(f"hinge fixture is invalid: {errors}")
        cls._tmp = tempfile.TemporaryDirectory(dir=host)
        try:
            source = generate(spec, "blockout")
            work = Path(cls._tmp.name)
            compiled, _path = compile_generated_module(source, work)
            if compiled.returncode:
                raise RuntimeError(f"generated TypeScript compilation failed:\n{compiled.stderr}")
            execution = subprocess.run(
                ["node", "--input-type=module", "--eval", PROBE],
                cwd=work, capture_output=True, text=True,
            )
            if execution.returncode:
                raise RuntimeError(f"Three.js runtime probe failed:\n{execution.stderr}")
            cls.result = json.loads(execution.stdout.strip().splitlines()[-1])
        except Exception:
            cls._tmp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def assertVecNear(self, actual, expected):
        self.assertEqual(len(actual), 3)
        for index, (got, want) in enumerate(zip(actual, expected)):
            self.assertAlmostEqual(got, want, places=5,
                                   msg=f"axis {index}: {actual} != {expected}")

    def test_unfolded_center_is_preserved_and_hinges_are_exposed(self):
        self.assertVecNear(self.result["authored"], [1, 0, 0])
        self.assertVecNear(self.result["rest"]["panel"], [1, 0, 0])
        self.assertVecNear(self.result["rest"]["flap"], [2, 0, 0])
        self.assertEqual(self.result["hingeCount"], 3)
        self.assertEqual(self.result["componentCount"], 6)  # root + five components

    def test_quarter_and_right_angle_about_vertical_edge(self):
        root_two = math.sqrt(0.5)
        self.assertVecNear(self.result["fortyFive"], [root_two, 0, -root_two])
        self.assertVecNear(self.result["ninety"], [0, 0, -1])

    def test_arbitrarily_directed_hinge_axis(self):
        self.assertVecNear(self.result["arbitraryAxis"], [0, 1, 0])

    def test_nested_hinges_compose_in_parent_frame(self):
        self.assertVecNear(self.result["nested"], [0, 1, -1])

    def test_sampled_signed_sweep_catches_intermediate_collision(self):
        positive = self.result["positiveSweep"]
        negative = self.result["negativeSweep"]
        self.assertEqual(len(positive), 7)
        self.assertEqual(len(negative), 7)
        self.assertFalse(positive[0])
        self.assertFalse(positive[-1])
        self.assertTrue(positive[3], "positive fold must touch blocker at 90 degrees")
        self.assertFalse(any(negative), "negative fold must pass on the clear side")


if __name__ == "__main__":
    unittest.main()
