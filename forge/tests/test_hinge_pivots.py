#!/usr/bin/env python3
"""Regression tests for parent-frame hinges in generated Three.js factories.

The emitted hierarchy is tested as code; a browser swept-motion render is a
separate visual acceptance gate before upstream promotion.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage2_spec"))
sys.path.insert(0, str(ROOT / "forge" / "stage3_build"))
from generate_threejs_factory import generate  # noqa: E402
from validate_sculpt_spec import validate_spec  # noqa: E402


class OffCenterHingeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory()
        spec_path = Path(cls.workspace.name) / "carton.json"
        create = subprocess.run(
            [sys.executable, str(ROOT / "forge" / "stage2_spec" / "new_sculpt_spec.py"),
             "Folding Carton", "--out", str(spec_path)],
            capture_output=True, text=True, check=False,
        )
        if create.returncode:
            raise RuntimeError(f"failed to create spec: {create.stderr}")
        cls.baseline = json.loads(spec_path.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def sample(self):
        spec = copy.deepcopy(self.baseline)
        # Keep one root: new_sculpt_spec can change its initial layout without
        # affecting the hinge-specific assertions.
        component = spec["componentTree"][0]
        component["id"] = "lid"
        component["name"] = "Lid"
        component["parent"] = None
        component["primitive"] = "box"
        component["transform"] = {
            "position": [0.8, 0, 0],
            "rotation": [0, 0, 0],
            "scale": [1, 1, 1],
        }
        spec["componentTree"] = [component]
        return spec

    @staticmethod
    def hinge(start=None, end=None, angle=0):
        return {
            "axisStart": [0, 0, 0] if start is None else start,
            "axisEnd": [0, 1, 0] if end is None else end,
            "restAngleDeg": angle,
        }

    def test_ordinary_factory_preserves_runtime_and_direct_parenting(self):
        spec = self.sample()
        errors, _ = validate_spec(spec)
        self.assertEqual(errors, [])
        output = generate(spec, "blockout")
        self.assertNotIn("const hinges:", output)
        self.assertNotIn("__hingeJoint", output)
        self.assertIn(
            "root.userData.sculptRuntime = { nodes, meshes, sockets, colliders, destructionGroups }",
            output,
        )
        self.assertRegex(output, r'\(nodes\["root"\] \?\? root\)\.add\(node_')

    def test_hinge_emits_axis_aligned_rotation_and_preserves_component_origin(self):
        spec = self.sample()
        spec["componentTree"][0]["hinge"] = self.hinge(angle=90)
        errors, _ = validate_spec(spec)
        self.assertEqual(errors, [])
        output = generate(spec, "blockout")
        self.assertIn("const hinges: Record<string, THREE.Group> = {};", output)
        self.assertIn("hinges: Record<string, THREE.Group>;", output)
        self.assertIn("THREE.MathUtils.degToRad(90.0)", output)
        self.assertIn("new THREE.Vector3(0, 1, 0)", output)
        self.assertIn(".quaternion.setFromUnitVectors(", output)
        self.assertRegex(output, r"hingeRestore_\w+\.quaternion\.copy\(hingeFrame_\w+\.quaternion\)\.invert\(\)")
        self.assertRegex(output, r"hingeOffset_\w+\.position\.copy\(hingePivot_\w+\.position\)\.negate\(\)")
        self.assertRegex(output, r"hingeRestore_\w+\.add\(hingeOffset_\w+\)")
        self.assertRegex(output, r"hingeOffset_\w+\.add\(node_\w+\)")
        self.assertNotRegex(output, r"node_\w+\.position\.sub\(hingePivot_")
        self.assertRegex(output, r'hinges\["lid"\] = hingeJoint_')
        self.assertIn("destructionGroups, hinges } satisfies ProceduralModelRuntime", output)

    def test_arbitrary_axis_and_nested_hinges_follow_component_hierarchy(self):
        spec = self.sample()
        lid = spec["componentTree"][0]
        lid["hinge"] = self.hinge([0.1, 0.2, 0.3], [0.1, 0.2, 1.3], -35)
        flap = copy.deepcopy(lid)
        flap["id"] = "flap"
        flap["name"] = "Tuck flap"
        flap["parent"] = "lid"
        flap["transform"]["position"] = [0.4, 0, 0]
        flap["hinge"] = self.hinge([0, 0, 0], [1, 1, 0], 25)
        spec["componentTree"].append(flap)

        errors, _ = validate_spec(spec)
        self.assertEqual(errors, [])
        output = generate(spec, "blockout")
        self.assertRegex(output, r'\(nodes\["lid"\] \?\? root\)\.add\(hingePivot_flap_')
        self.assertIn("THREE.MathUtils.degToRad(-35.0)", output)
        self.assertIn("THREE.MathUtils.degToRad(25.0)", output)
        self.assertIn('hinges["lid"]', output)
        self.assertIn('hinges["flap"]', output)
        self.assertEqual(len(re.findall(r'hinges\["(?:lid|flap)"\] =', output)), 2)

    def test_endpoint_derived_component_still_gets_hinge_after_original_position(self):
        spec = self.sample()
        component = spec["componentTree"][0]
        component["primitive"] = "cylinder"
        component["attachment"] = {
            "parentSocket": "root",
            "localStart": [0.2, 0.1, 0.0],
            "localEnd": [0.2, 0.8, 0.0],
            "contactType": "surface",
            "embedDepth": 0.01,
            "gapTolerance": 0.05,
        }
        component["hinge"] = self.hinge()
        errors, _ = validate_spec(spec)
        self.assertEqual(errors, [])
        output = generate(spec, "blockout")
        self.assertLess(output.find(".position.copy(endpoint_"), output.find(".position.copy(hingePivot_"))

    def test_rejects_bad_axes_and_angles_before_codegen(self):
        bad = [
            (None, "must be an object"),
            ({}, "axisStart"),
            (self.hinge([0, 0, 0], [0, 0, 0]), "nonzero"),
            (self.hinge([0, 0, 0], [0, 1e-9, 0]), "nonzero"),
            (self.hinge([True, 0, 0], [0, 1, 0]), "axisStart"),
            (self.hinge([0, 0, 0], ["x", 1, 0]), "axisEnd"),
            (self.hinge([0, 0, 0], [0, 1, 0], float("nan")), "restAngleDeg"),
            (self.hinge([0, 0, 0], [0, 1, 0], float("inf")), "restAngleDeg"),
            (self.hinge([0, 0, 0], [0, 1, 0], True), "restAngleDeg"),
            ({**self.hinge(), "magic": "unimplemented"}, "unsupported fields"),
        ]
        for invalid, reason in bad:
            with self.subTest(reason=reason, value=invalid):
                spec = self.sample()
                spec["componentTree"][0]["hinge"] = invalid
                errors, _ = validate_spec(spec)
                self.assertTrue(
                    any("hinge" in error and reason in error for error in errors),
                    errors,
                )
                with self.assertRaisesRegex(ValueError, "hinge"):
                    generate(spec, "blockout")

    def test_bone_skinned_component_rejects_hinge(self):
        spec = self.sample()
        spec['componentTree'][0]['hinge'] = self.hinge()
        spec.setdefault('preSpecAssessment', {}).setdefault('objectClass', {})['primaryDomain'] = 'character'
        spec['rig'] = {'bones': [{'id': 'lid-bone', 'component': 'lid', 'jointPos': [0, 0, 0]}]}
        errors, _ = validate_spec(spec)
        self.assertTrue(any('hinge' in e and 'bone-track' in e for e in errors), errors)

    def test_cli_emits_hinge_as_opt_in_without_additional_dependencies(self):
        spec = self.sample()
        spec["componentTree"][0]["hinge"] = self.hinge(angle=40)
        with tempfile.TemporaryDirectory() as folder:
            spec_file = Path(folder) / "spec.json"
            ts_file = Path(folder) / "carton.ts"
            spec_file.write_text(json.dumps(spec), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "stage3_build" / "generate_threejs_factory.py"),
                 str(spec_file), "--out", str(ts_file), "--allow-nonstrict"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(ts_file.exists())
            self.assertIn('hinges["lid"]', ts_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
