#!/usr/bin/env python3
"""The fitted result and final telemetry must agree at a tight render budget."""

import unittest
from pathlib import Path

from forge.stage4_review.fit_params import FitConfig, fit, fit_against_divine_eye


class BudgetHistoryTest(unittest.TestCase):
    def test_prior_coordinate_improvement_is_recorded_at_budget_limit(self):
        result = fit(
            (0.0, 0.0), ((-1.0, 1.0),) * 2,
            lambda parameters: 0.5 + parameters[0], FitConfig(max_evaluations=3),
        )
        self.assertEqual(result.status, "max-evaluations")
        self.assertEqual(result.evaluations, 3)
        self.assertEqual(result.parameters, (0.5, 0.0))
        self.assertEqual(result.best_score, 1.0)
        self.assertEqual(result.iterations, 1)
        self.assertEqual([row.best_score for row in result.history], [0.5, 1.0])
        self.assertTrue(result.history[-1].improved)
        self.assertEqual(result.history[-1].evaluations, 3)
        self.assertEqual([row["fidelity"] for row in result.to_correction_history()], [0.5, 1.0])

    def test_no_improvement_does_not_invent_iteration(self):
        result = fit(
            (0.0, 0.0), ((-1.0, 1.0),) * 2,
            lambda _parameters: 0.5, FitConfig(max_evaluations=3),
        )
        self.assertEqual(result.iterations, 0)
        self.assertEqual(result.best_score, 0.5)
        self.assertEqual(len(result.history), 1)
        self.assertFalse(result.history[-1].improved)

    def test_partial_current_coordinate_commit_remains_recorded(self):
        result = fit(
            (0.0,), ((-1.0, 1.0),),
            lambda parameters: 0.5 - parameters[0], FitConfig(max_evaluations=2),
        )
        self.assertEqual(result.best_score, 1.0)
        self.assertEqual(result.iterations, 1)
        self.assertEqual(result.history[-1].best_score, 1.0)

    def test_all_budget_boundaries_keep_terminal_telemetry_authoritative(self):
        # Cover exhaustion at initial, negative and positive probes, between
        # coordinates, and during later iterations without inventing work.
        for dimensions in (1, 2, 3, 5):
            initial = (0.0,) * dimensions
            bounds = ((-1.0, 1.0),) * dimensions
            target = tuple(0.5 if index % 2 == 0 else -0.5 for index in range(dimensions))
            objectives = (
                lambda values: 0.5 + 0.1 * sum(values),
                lambda values: 1.0 - sum((value - target[index]) ** 2 for index, value in enumerate(values)),
                lambda _values: 0.5,
            )
            for budget in range(1, 2 * dimensions + 6):
                for objective in objectives:
                    with self.subTest(dimensions=dimensions, budget=budget, objective=objectives.index(objective)):
                        result = fit(
                            initial, bounds, objective,
                            FitConfig(max_iterations=4, max_evaluations=budget, plateau_iterations=2),
                        )
                        self.assertLessEqual(result.evaluations, budget)
                        self.assertEqual(result.history[-1].evaluations, result.evaluations)
                        self.assertEqual(result.history[-1].iteration, result.iterations)
                        self.assertEqual(result.history[-1].best_score, result.best_score)
                        self.assertEqual(
                            [row.best_score for row in result.history],
                            sorted(row.best_score for row in result.history),
                        )

    def test_divine_eye_selected_fidelity_matches_final_fit_history(self):
        def render(parameters):
            return Path(f"render-{parameters[0]}-{parameters[1]}.png")

        def evaluate(_reference, rendered):
            if rendered.name == "render-0.5-0.0.png":
                return {"fidelity": 0.95, "hardGateFailures": []}
            return {"fidelity": 0.80, "hardGateFailures": []}

        result = fit_against_divine_eye(
            (0.0, 0.0), ((-1.0, 1.0),) * 2, render,
            "reference.png", evaluate, FitConfig(max_evaluations=3),
        )
        self.assertEqual(result.best_raw_fidelity, 0.95)
        self.assertEqual(result.fit_result.best_score, 0.95)
        self.assertEqual(result.fit_result.history[-1].best_score, 0.95)
        self.assertEqual(result.fit_result.iterations, 1)
        self.assertEqual(result.fit_result.evaluations, 3)


if __name__ == "__main__":
    unittest.main()
