"""Fail-closed parent cycle detection while preserving forward references.

The generator must preserve parent-first emission for valid unordered
component trees and reject invalid cycles without unbounded recursion.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for directory in ("_shared", "stage2_spec", "stage3_build", "tests"):
    sys.path.insert(0, str(ROOT / "forge" / directory))

from generate_threejs_factory import filter_components_for_pass, generate  # noqa: E402
from test_attachment_does_not_override_primitive import spec_with  # noqa: E402
from validate_sculpt_spec import validate_spec  # noqa: E402


def fixture() -> dict:
    return spec_with("box", "assembled-solid")


class ComponentParentCycleTests(unittest.TestCase):
    def test_child_may_precede_parent_and_remains_parented(self) -> None:
        spec = fixture()
        spec["componentTree"].reverse()
        errors, _warnings = validate_spec(spec)
        self.assertEqual(errors, [])
        resolved = filter_components_for_pass(spec, spec["componentTree"], "blockout")
        self.assertEqual([component["id"] for component in resolved], ["body", "part"])
        source = generate(spec, "blockout")
        self.assertLess(source.index('nodes["body"] ='),
                        source.index('(nodes["body"] ?? root).add('))

    def test_self_cycle_is_rejected_by_validator_and_direct_generator(self) -> None:
        spec = fixture()
        spec["componentTree"][1]["parent"] = "part"
        errors, _warnings = validate_spec(spec)
        self.assertTrue(any("parent cycle" in error and "part" in error
                            for error in errors), errors)
        with self.assertRaisesRegex(ValueError, "parent cycle"):
            generate(spec, "blockout")

    def test_two_component_cycle_is_rejected(self) -> None:
        spec = fixture()
        spec["componentTree"][0]["parent"] = "part"
        errors, _warnings = validate_spec(spec)
        self.assertTrue(any("parent cycle" in error for error in errors), errors)
        with self.assertRaisesRegex(ValueError, "body.*part|part.*body"):
            filter_components_for_pass(spec, spec["componentTree"], "blockout")

    def test_three_component_cycle_is_reported_once(self) -> None:
        spec = fixture()
        child = copy.deepcopy(spec["componentTree"][1])
        child["id"], child["name"], child["parent"] = "flap", "Flap", "part"
        spec["componentTree"].append(child)
        spec["componentTree"][0]["parent"] = "flap"
        errors, _warnings = validate_spec(spec)
        cycles = [error for error in errors if "parent cycle" in error]
        self.assertEqual(len(cycles), 1, cycles)
        for name in ("body", "part", "flap"):
            self.assertIn(name, cycles[0])
        with self.assertRaisesRegex(ValueError, "parent cycle"):
            generate(spec, "blockout")

    def test_missing_parent_error_remains_distinct(self) -> None:
        spec = fixture()
        spec["componentTree"][1]["parent"] = "absent"
        errors, _warnings = validate_spec(spec)
        self.assertTrue(any("missing parent" in error for error in errors))
        self.assertFalse(any("parent cycle" in error for error in errors))

    def test_long_valid_forward_chain_never_recurses(self) -> None:
        length = 1800
        components = [
            {"id": f"n{i}", "level": "macro",
             "parent": f"n{i + 1}" if i + 1 < length else None}
            for i in range(length)
        ]
        resolved = filter_components_for_pass({}, components, "blockout")
        self.assertEqual(len(resolved), length)
        self.assertEqual(resolved[0]["id"], f"n{length - 1}")
        self.assertEqual(resolved[-1]["id"], "n0")

    def test_seeded_acyclic_dags_match_original_recursive_order(self) -> None:
        # Differential regression against the old recursion on VALID small
        # DAGs. It is safe as an oracle here because parents are acyclic and
        # fewer than 50 deep; invalid cycles are tested separately above.
        from random import Random

        rng = Random(0xC1C1E)

        def original_order(components: list[dict]) -> list[str]:
            by_id = {str(item["id"]): item for item in components}
            visited: set[str] = set()
            emitted: list[str] = []

            def visit(item: dict) -> None:
                component_id = str(item["id"])
                if component_id in visited:
                    return
                parent = item.get("parent")
                if parent in by_id:
                    visit(by_id[parent])
                emitted.append(component_id)
                visited.add(component_id)

            for item in components:
                if item.get("level") == "macro":
                    visit(item)
            if not emitted and components:
                emitted.append(str(components[0]["id"]))
            return emitted

        for trial in range(100):
            nodes: list[dict] = []
            count = rng.randrange(2, 49)
            for index in range(count):
                parent = (
                    f"n{rng.randrange(index)}"
                    if index and rng.randrange(4) != 0 else None
                )
                nodes.append({
                    "id": f"n{index}", "parent": parent,
                    "level": rng.choice(("macro", "macro", "meso", "micro")),
                })
            rng.shuffle(nodes)
            result = filter_components_for_pass({}, nodes, "blockout")
            result_ids = [str(item["id"]) for item in result]
            self.assertEqual(
                result_ids, original_order(nodes),
                f"valid DAG case {trial}: parent-first output order changed",
            )
            positions = {component_id: index
                         for index, component_id in enumerate(result_ids)}
            for node in result:
                parent = node.get("parent")
                if parent in positions:
                    self.assertLess(
                        positions[parent], positions[node["id"]],
                        f"case {trial}: parent emitted after child",
                    )

    def test_multiple_disconnected_parent_cycles_each_report_once(self) -> None:
        spec = fixture()
        first, second = spec["componentTree"]
        first["parent"] = first["id"]
        second["parent"] = second["id"]
        errors, _warnings = validate_spec(spec)
        cycles = [item for item in errors if "parent cycle" in item]
        self.assertEqual(len(cycles), 2, cycles)

    def test_order_for_existing_parent_first_specs_is_unchanged(self) -> None:
        spec = fixture()
        resolved = filter_components_for_pass(spec, spec["componentTree"], "blockout")
        self.assertEqual([component["id"] for component in resolved], ["body", "part"])
        child = copy.deepcopy(spec["componentTree"][1])
        child["id"], child["name"], child["parent"] = "sibling", "Sibling", "body"
        spec["componentTree"].append(child)
        resolved = filter_components_for_pass(spec, spec["componentTree"], "blockout")
        self.assertEqual([component["id"] for component in resolved],
                         ["body", "part", "sibling"])


if __name__ == "__main__":
    unittest.main()
