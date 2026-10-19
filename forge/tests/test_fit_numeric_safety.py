#!/usr/bin/env python3
"""Finite bounded fitting must not emit Infinity steps or crash on large integers."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from forge.stage4_review.fit_params import (
    FitConfig, FitInputError, NonFiniteScoreError, fit, main,
)


class NumericSafetyTest(unittest.TestCase):
    def test_finite_endpoints_with_infinite_span_fail_before_objective(self):
        calls = []
        with self.assertRaises(FitInputError) as caught:
            fit((0.0,), ((-1e308, 1e308),),
                lambda xs: calls.append(xs) or 0.5, FitConfig(max_evaluations=3))
        self.assertEqual(caught.exception.field, "bounds[0]")
        self.assertIn("span", str(caught.exception))
        self.assertEqual(calls, [])

    def test_overlarge_int_in_initial_and_bounds_is_an_input_error(self):
        very_large = 10 ** 500
        for initial, bounds, field in [
            ((very_large,), ((-1.0, 1.0),), "initial[0]"),
            ((0.0,), ((-very_large, 1.0),), "bounds[0][0]"),
            ((0.0,), ((-1.0, very_large),), "bounds[0][1]"),
        ]:
            with self.subTest(field=field), self.assertRaises(FitInputError) as caught:
                fit(initial, bounds, lambda _: 0.5)
            self.assertEqual(caught.exception.field, field)

    def test_overlarge_objective_integer_is_a_scored_error_not_overflow(self):
        with self.assertRaises(NonFiniteScoreError):
            fit((0.0,), ((-1.0, 1.0),), lambda _: 10 ** 500)

    def test_huge_minimum_improvement_fails_before_first_objective(self):
        calls = []
        with self.assertRaises(FitInputError) as caught:
            fit((0.0,), ((-1.0, 1.0),),
                lambda xs: calls.append(xs) or 0.5,
                FitConfig(min_improvement=10 ** 500))
        self.assertEqual(caught.exception.field, "config.min_improvement")
        self.assertEqual(calls, [])

    def test_cli_overlarge_numbers_return_controlled_exit_code(self):
        payload = {
            "initial": [0.0], "bounds": [[-1.0, 1.0]],
            "target": [10 ** 500], "config": {},
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fit.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            err = io.StringIO()
            with redirect_stderr(err):
                result = main(["--input", str(path), "--json"])
            self.assertEqual(result, 2)
            self.assertIn("target", err.getvalue())
            self.assertNotIn("Traceback", err.getvalue())

    def test_normal_bounds_preserve_deterministic_order_and_finite_telemetry(self):
        result = fit((0.0, 0.0), ((-1.0, 1.0), (-1.0, 1.0)),
                     lambda values: 1.0 - (values[0] - 0.5) ** 2,
                     FitConfig(max_evaluations=3, coordinate_order=(1, 0)))
        report = result.to_json()
        self.assertEqual(report["coordinateOrder"], [1, 0])
        # JSON should be standards-compliant, including every step-size value.
        json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
