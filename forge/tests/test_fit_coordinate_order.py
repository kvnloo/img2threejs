#!/usr/bin/env python3
"""Regression tests for deterministic coordinate order in bounded fitting."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from forge.stage4_review.fit_params import FitConfig, FitInputError, fit, fit_against_divine_eye, main


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

    def test_divine_eye_gate_rejection_with_priority(self):
        probes = []

        def render(parameters):
            probes.append(parameters)
            return Path(f"render-{parameters[0]}-{parameters[1]}.png")

        def evaluator(_reference, render_path):
            if render_path.name == "render-0.0--0.5.png":
                return {"fidelity": 0.99, "hardGateFailures": ["scale"]}
            if render_path.name == "render-0.0-0.0.png":
                return {"fidelity": 0.85, "hardGateFailures": []}
            return {"fidelity": 0.70, "hardGateFailures": []}

        result = fit_against_divine_eye(
            (0.0, 0.0), ((-1.0, 1.0),) * 2, render, "reference.png", evaluator,
            FitConfig(max_evaluations=3, coordinate_order=(1, 0)),
        )
        self.assertEqual(probes[:3], [(0.0, 0.0), (0.0, -0.5), (0.0, 0.5)])
        self.assertEqual(result.fit_result.parameters, (0.0, 0.0))
        self.assertEqual(result.fit_result.best_score, 0.85)
        self.assertEqual(result.best_raw_fidelity, 0.85)
        self.assertEqual(result.to_json()["fitResult"]["coordinateOrder"], [1, 0])
        self.assertEqual(result.correction_history[1]["hardGateFailures"], ["scale"])

    def test_cli_priority_and_malformed_order(self):
        payload = {
            "initial": [0.0, 0.0, 0.0],
            "bounds": [[-1.0, 1.0]] * 3,
            "target": [0.0, 0.0, 0.5],
            "config": {"maxEvaluations": 3, "coordinateOrder": [2, 0, 1]},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fit.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main(["--input", str(path), "--json"]), 0)
            value = json.loads(stdout.getvalue())
            self.assertEqual(value["coordinateOrder"], [2, 0, 1])
            self.assertEqual(value["bestScore"], 1.0)
            payload["config"]["coordinateOrder"] = [2, 2, 0]
            path.write_text(json.dumps(payload), encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(main(["--input", str(path), "--json"]), 2)
            self.assertIn("config.coordinate_order", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
