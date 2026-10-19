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
