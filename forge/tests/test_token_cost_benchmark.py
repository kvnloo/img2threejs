#!/usr/bin/env python3
"""Regression tests for the measured-usage benchmark (stdlib only)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import benchmark_token_cost as bench


def event(stage, index, run="a"):
    return {
        "run_id": run, "event_id": str(index), "stage": stage,
        "model": "fixture-model", "provider": "fixture",
        "usage_source": "provider",
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }


def completed(run="a"):
    return [event(stage, i, run) for i, stage in enumerate(sorted(bench.REQUIRED))]


class MeasuredUsageTest(unittest.TestCase):
    def test_complete_run(self):
        report = bench.aggregate(completed())
        self.assertEqual(report["runCount"], 1)
        self.assertEqual(report["totalTokens"], 48)
        self.assertEqual(report["unpricedRequests"], 4)

    def test_multiple_runs(self):
        self.assertEqual(bench.aggregate(completed("a") + completed("b"))["runCount"], 2)

    def test_incomplete_run(self):
        with self.assertRaisesRegex(ValueError, "incomplete reconstruction"):
            bench.aggregate(completed()[:-1])

    def test_no_guessed_usage(self):
        rows = completed()
        rows[0]["usage_source"] = "estimated"
        with self.assertRaisesRegex(ValueError, "not provider-measured"):
            bench.aggregate(rows)

    def test_duplicate_receipt(self):
        rows = completed()
        with self.assertRaisesRegex(ValueError, "duplicate receipt"):
            bench.aggregate(rows + [rows[0]])

    def test_invalid_counts_and_cost(self):
        for bad in (True, -1, 1.5):
            rows = completed()
            rows[0]["usage"]["prompt_tokens"] = bad
            with self.assertRaises(ValueError):
                bench.aggregate(rows)
        for bad in ("NaN", "-1", True):
            rows = completed()
            rows[0]["cost_usd"] = bad
            with self.assertRaises(ValueError):
                bench.aggregate(rows)

    def test_cost_not_assumed_free(self):
        rows = completed()
        rows[0]["cost_usd"] = "0.003"
        report = bench.aggregate(rows)
        self.assertEqual(report["unpricedRequests"], 3)
        self.assertEqual(report["byStage"][rows[0]["stage"]]["knownCostUsd"], "0.003")

    def test_cli_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "in.jsonl"
            dest = root / "out.json"
            data.write_text("\n".join(json.dumps(r) for r in completed()), encoding="utf-8")
            self.assertEqual(bench.main([str(data), "--out", str(dest)]), 0)
            first = dest.read_bytes()
            self.assertEqual(bench.main([str(data), "--out", str(dest)]), 0)
            self.assertEqual(first, dest.read_bytes())

    def test_cli_minimum_runs_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data, dest = root / "in.jsonl", root / "out.json"
            data.write_text("\n".join(json.dumps(r) for r in completed()), encoding="utf-8")
            self.assertEqual(bench.main([str(data), "--out", str(dest), "--minimum-runs", "2"]), 2)
            self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
