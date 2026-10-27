import unittest

from replay import (
    CoordinatePriorityPolicy,
    Node,
    ReplayError,
    World,
    evaluate_policy,
    learn_coordinate_priority,
    promote_if_no_regression,
    replay,
)


def world(world_id: str, coordinate_one_gain: float = 0.18) -> World:
    return World(
        id=world_id,
        root_id="root",
        nodes=(
            Node("root", None, None, None, None, 0.60),
            Node("c0-", "root", 0, -1, 0.25, 0.61),
            Node("c0+", "root", 0, 1, 0.25, 0.62),
            Node("c1-", "root", 1, -1, 0.25, 0.60 + coordinate_one_gain),
            Node("c1+", "root", 1, 1, 0.25, 0.58),
            Node("c1-deep", "c1-", 1, -1, 0.125, min(0.99, 0.60 + coordinate_one_gain + 0.10)),
        ),
    )


class ReplayTest(unittest.TestCase):
    def test_replay_is_budget_bounded_and_only_visits_recorded_nodes(self):
        result = replay(world("w"), CoordinatePriorityPolicy((1, 0)), budget=3)
        self.assertLessEqual(result.spent, 3)
        self.assertTrue(set(result.visited) <= {"root", "c0-", "c0+", "c1-", "c1+", "c1-deep"})

    def test_history_learns_high_gain_coordinate(self):
        order = learn_coordinate_priority((world("a"), world("b", 0.20)))
        self.assertEqual(order[0], 1)

    def test_coordinate_learning_uses_best_direction_instead_of_cancelling(self):
        directional = World(
            id="directional",
            root_id="root",
            nodes=(
                Node("root", None, None, None, None, 0.50),
                Node("c0-", "root", 0, -1, 0.25, 0.49),
                Node("c0+", "root", 0, 1, 0.25, 0.70),
                Node("c1-", "root", 1, -1, 0.25, 0.58),
                Node("c1+", "root", 1, 1, 0.25, 0.58),
            ),
        )
        self.assertEqual(learn_coordinate_priority((directional,))[0], 0)

    def test_root_only_learning_ignores_deep_branch_selection_bias(self):
        biased = World(
            id="biased",
            root_id="root",
            nodes=(
                Node("root", None, None, None, None, 0.50),
                Node("c0", "root", 0, 1, 0.25, 0.55),
                Node("c1", "root", 1, 1, 0.25, 0.65),
                Node("c0-deep-1", "c0", 0, 1, 0.125, 0.90),
                Node("c0-deep-2", "c0-deep-1", 0, 1, 0.0625, 0.99),
            ),
        )
        self.assertEqual(learn_coordinate_priority((biased,))[0], 1)
        self.assertEqual(learn_coordinate_priority((biased,), root_only=False)[0], 0)

    def test_learned_order_improves_iou_at_equal_budget(self):
        target = world("holdout")
        fixed = CoordinatePriorityPolicy((0, 1), name="fixed")
        learned = CoordinatePriorityPolicy((1, 0), name="learned")
        fixed_result = replay(target, fixed, budget=2)
        learned_result = replay(target, learned, budget=2)
        self.assertGreater(learned_result.best_clean_iou, fixed_result.best_clean_iou)
        self.assertEqual(learned_result.spent, fixed_result.spent)

    def test_hard_gated_high_iou_node_cannot_win(self):
        gated = World(
            id="gated",
            root_id="root",
            nodes=(
                Node("root", None, None, None, None, 0.70),
                Node("bad", "root", 0, -1, 0.25, 0.99, ("scale",)),
                Node("good", "root", 1, -1, 0.25, 0.82),
            ),
        )
        result = replay(gated, CoordinatePriorityPolicy((0, 1)), budget=3)
        self.assertEqual(result.best_node_id, "good")
        self.assertEqual(result.best_clean_iou, 0.82)

    def test_policy_cannot_select_unrecorded_counterfactual(self):
        class BadPolicy:
            name = "bad"

            def choose(self, observation):
                return "invented"

        with self.assertRaisesRegex(ReplayError, "out-of-support"):
            replay(world("w"), BadPolicy(), budget=2)

    def test_no_regression_tie_keeps_incumbent(self):
        worlds = (world("a"), world("b"))
        incumbent = CoordinatePriorityPolicy((1, 0), name="incumbent")
        tied = CoordinatePriorityPolicy((1, 0), name="candidate")
        self.assertIs(promote_if_no_regression(worlds, incumbent, tied, budget=3), incumbent)

    def test_policy_report_is_deterministic(self):
        worlds = (world("a"), world("b"))
        policy = CoordinatePriorityPolicy((1, 0), name="learned")
        self.assertEqual(evaluate_policy(worlds, policy, 3), evaluate_policy(worlds, policy, 3))


if __name__ == "__main__":
    unittest.main()
