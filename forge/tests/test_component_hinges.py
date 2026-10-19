"""Regression tests for optional parent-frame hinges in generated Three.js factories.

Refs img2threejs/img2threejs#118; reproducer reported by @mariusargint.
"""

from __future__ import annotations

import copy
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "forge" / "tests", ROOT / "forge" / "_shared",
             ROOT / "forge" / "stage2_spec", ROOT / "forge" / "stage3_build"):
    sys.path.insert(0, str(path))

from generate_threejs_factory import generate  # noqa: E402
from test_attachment_does_not_override_primitive import spec_with  # noqa: E402
from validate_sculpt_spec import validate_spec  # noqa: E402


def _spec() -> dict:
    spec = spec_with("box", "assembled-solid")
    spec["componentTree"][1]["hinge"] = {
        "axisStart": [-0.45, 0.4, 0.6],
        "axisEnd": [-0.45, 1.4, 0.6],
        "restAngleDeg": 90,
    }
    return spec


class ComponentHingeTests(unittest.TestCase):
    def test_valid_hinge_round_trips_to_runtime(self) -> None:
        spec = _spec()
        self.assertEqual(validate_spec(spec)[0], [])
        source = generate(spec, "blockout")
        self.assertIn("hinges: Record<string, THREE.Group>;", source)
        self.assertIn("const hinges: Record<string, THREE.Group> = {};", source)
        self.assertIn("hinge_anchor_part_1.position.set(-0.45, 0.4, 0.6);", source)
        self.assertIn("hinge_rotation_part_1.rotation.y = " + str(math.pi / 2), source)
        self.assertIn("hinge_counter_part_1.quaternion.copy(hinge_anchor_part_1.quaternion).invert();", source)
        self.assertIn("node_part_1.position.sub(hinge_anchor_part_1.position);", source)
        self.assertIn('(nodes["body"] ?? root).add(hinge_anchor_part_1);', source)
        self.assertIn('hinges["part"] = hinge_rotation_part_1;', source)
        self.assertIn("destructionGroups, hinges } satisfies ProceduralModelRuntime;", source)
        self.assertIn('nodes["part"] = node_part_1;', source)

    def test_unhinged_models_keep_the_legacy_emission_path(self) -> None:
        source = generate(spec_with("box", "assembled-solid"), "blockout")
        self.assertNotIn("const hinges:", source)
        self.assertNotIn("hinge_anchor_", source)
        self.assertIn('(nodes["body"] ?? root).add(node_part_1);', source)
        self.assertIn("colliders, destructionGroups } satisfies ProceduralModelRuntime;", source)

    def test_parent_local_axis_is_not_limited_to_world_y(self) -> None:
        spec = _spec()
        spec["componentTree"][1]["hinge"]["axisEnd"] = [-0.45, 0.4, 1.6]
        source = generate(spec, "blockout")
        self.assertIn("setFromUnitVectors(", source)
        self.assertIn(".sub(hinge_anchor_part_1.position).normalize(),", source)
        self.assertIn("hinge_counter_part_1.add(node_part_1);", source)

    def test_nested_hinges_keep_existing_child_attachment_target(self) -> None:
        spec = _spec()
        flap = copy.deepcopy(spec["componentTree"][1])
        flap["id"], flap["name"], flap["parent"] = "flap", "Flap", "part"
        flap["hinge"] = {
            "axisStart": [0.0, 0.5, 0.0],
            "axisEnd": [0.0, 0.5, 1.0],
            "restAngleDeg": -45,
        }
        spec["componentTree"].append(flap)
        self.assertEqual(validate_spec(spec)[0], [])
        source = generate(spec, "blockout")
        self.assertIn('(nodes["part"] ?? root).add(hinge_anchor_flap_2);', source)
        self.assertIn('hinges["part"] = hinge_rotation_part_1;', source)
        self.assertIn('hinges["flap"] = hinge_rotation_flap_2;', source)

    def test_attachment_endpoint_placement_survives_hinging(self) -> None:
        spec = spec_with("cylinder", "assembled-solid")
        spec["componentTree"][1]["hinge"] = _spec()["componentTree"][1]["hinge"]
        source = generate(spec, "blockout")
        self.assertIn("node_part_1.position.copy(endpoint_part_1.start);", source)
        self.assertIn("node_part_1.position.sub(hinge_anchor_part_1.position);", source)
        self.assertIn("mesh_part_1.quaternion.copy(endpoint_part_1.quaternion);", source)

    def test_invalid_hinge_payloads_fail_at_spec_validation(self) -> None:
        valid = _spec()["componentTree"][1]["hinge"]
        invalid = [
            None, "hinge", [], {},
            {"axisStart": [0, 0, 0]},
            {**valid, "axisStart": [0, 0]},
            {**valid, "axisEnd": [True, 0, 0]},
            {**valid, "axisEnd": valid["axisStart"]},
            {**valid, "axisEnd": [valid["axisStart"][0] + 1e-9, 0.4, 0.6]},
            {**valid, "restAngleDeg": "ninety"},
            {**valid, "restAngleDeg": float("nan")},
            {**valid, "restAngleDeg": float("inf")},
            {**valid, "axisStart": [float("inf"), 0, 0]},
        ]
        for bad in invalid:
            with self.subTest(hinge=bad):
                spec = _spec()
                spec["componentTree"][1]["hinge"] = bad
                errors, _warnings = validate_spec(spec)
                self.assertTrue(any("hinge" in message for message in errors), errors)

    def test_missing_rest_angle_defaults_to_zero(self) -> None:
        spec = _spec()
        spec["componentTree"][1]["hinge"].pop("restAngleDeg")
        self.assertEqual(validate_spec(spec)[0], [])
        self.assertIn("hinge_rotation_part_1.rotation.y = 0.0;", generate(spec, "blockout"))


if __name__ == "__main__":
    unittest.main()
