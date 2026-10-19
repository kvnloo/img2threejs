#!/usr/bin/env python3
"""Regression tests for deterministic coordinate order in bounded fitting."""

import unittest

from forge.stage4_review.fit_params import FitConfig, FitInputError, fit


def quadratic(target):
    return lambda values: 1.0 - sum((value - target[i]) ** 2 for i, value in enumerate(values))


class CoordinateOrderTest(unittest.TestCase):
    def test_priority_under_same_budget(self):
        initial = (0.0, 0.0, 0.0)
        bounds = ((-1.0, 1.0),) * 3
        objective = quadratic((0.0, 0.0, 0.5))
        baseline = fit(initial, bounds, objective, FitConfig(max_evaluations=3))
        priority = fit(initial, bounds, objective, FitConfig(max_evaluations=3, coordinate_order=(2, 0, 1)))
        self.assertEqual(baseline.evaluations, priority.evaluations)
        self.assertEqual(baseline.best_score, 0.75)
        self.assertEqual(priority.best_score, 1.0)
        self.assertEqual(priority.parameters, (0.0, 0.0, 0.5))
        self.assertEqual(priority.to_json()["coordinateOrder"], [2, 0, 1])

    def test_explicit_identity_equals_default(self):
        config = dict(max_iterations=8, max_evaluations=30, seed=42)
        args = ((0.0, 0.0), ((-1.0, 1.0),) * 2, quadratic((0.5, -0.5)))
        self.assertEqual(fit(*args, FitConfig(**config)), fit(*args, FitConfig(**config, coordinate_order=(0, 1))))

    def test_invalid_order_rejected_before_evaluation(self):
        called = []
        for order in ((), (0,), (0, 0), (0, 2), (-1, 1), (True, 1), (0.0, 1), "0,1", ([0], 1)):
            with self.subTest(order=order):
                with self.assertRaises(FitInputError) as raised:
                    fit((0.0, 0.0), ((-1.0, 1.0),) * 2, lambda x: called.append(x), FitConfig(coordinate_order=order))
                self.assertEqual(raised.exception.field, "config.coordinate_order")
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
