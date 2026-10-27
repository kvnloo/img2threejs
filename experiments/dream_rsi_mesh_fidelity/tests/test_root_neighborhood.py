import unittest
from pathlib import Path

from root_neighborhood import capture_root_neighborhood


class RootNeighborhoodTest(unittest.TestCase):
    def test_every_coordinate_direction_is_evaluated_from_same_root(self):
        rendered = []
        by_path = {}

        def render(parameters):
            rendered.append(parameters)
            path = Path(f"render-{len(rendered)}.png")
            by_path[path.name] = parameters
            return path

        def evaluator(_reference, render_path):
            values = by_path[render_path.name]
            iou = 0.5 + max(0.0, values[0]) * 0.1 + max(0.0, values[1]) * 0.3
            return {"signals": {"silhouetteIoU": iou}, "hardGateFailures": []}

        world = capture_root_neighborhood(
            world_id="fixture",
            initial=(0.0, 0.0),
            bounds=((-1.0, 1.0), (-1.0, 1.0)),
            render_for_parameters=render,
            reference_png="reference.png",
            evaluator=evaluator,
        )

        self.assertEqual(len(world.nodes), 5)
        self.assertTrue(all(node.parent_id == "root" for node in world.nodes[1:]))
        self.assertEqual(rendered[0], (0.0, 0.0))
        self.assertIn((-0.5, 0.0), rendered)
        self.assertIn((0.5, 0.0), rendered)
        self.assertIn((0.0, -0.5), rendered)
        self.assertIn((0.0, 0.5), rendered)

    def test_hard_gates_are_preserved(self):
        def render(parameters):
            return Path(f"render-{parameters[0]}.png")

        def evaluator(_reference, render_path):
            gated = render_path.stem.endswith("0.5")
            return {
                "signals": {"silhouetteIoU": 0.95 if gated else 0.70},
                "hardGateFailures": ["scale"] if gated else [],
            }

        world = capture_root_neighborhood(
            world_id="gated",
            initial=(0.0,),
            bounds=((-1.0, 1.0),),
            render_for_parameters=render,
            reference_png="reference.png",
            evaluator=evaluator,
        )
        self.assertTrue(any(node.hard_gate_failures == ("scale",) for node in world.nodes))


if __name__ == "__main__":
    unittest.main()
