#!/usr/bin/env python3
"""Provider-token A/B comparisons require measured, matched run conditions."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import benchmark_token_cost as bench  # noqa: E402


def run(identifier="same-image", *, tokens=12, cost="0.010"):
    records = []
    for index, stage in enumerate(sorted(bench.REQUIRED)):
        row = {
            "run_id": identifier, "event_id": f"call-{index}", "stage": stage,
            "model": "fixed-model", "provider": "fixed-provider", "usage_source": "provider",
            "usage": {"prompt_tokens": tokens - 2, "completion_tokens": 2, "total_tokens": tokens},
            "reference_sha256": "a" * 64, "render_profile_sha256": "b" * 64,
            "evaluator_revision": "eval-v1", "render_budget": 8,
        }
        if cost is not None:
            row["cost_usd"] = cost
        records.append(row)
    return records


class PairedUsageTest(unittest.TestCase):
    def test_paired_usage_delta_is_measured_not_quality(self):
        compared = bench.compare_paired(run(), run(tokens=10, cost="0.008"))
        self.assertEqual(compared["deltaTokens"], -8)
        self.assertEqual(compared["deltaCostUsd"], "-0.008")
        self.assertFalse(compared["qualityCompared"])
        self.assertEqual(compared["pairedRuns"]["same-image"]["deltaTokens"], -8)
        self.assertEqual(compared["pairedRuns"]["same-image"]["conditions"]["renderBudget"], 8)

    def test_unknown_price_never_becomes_free_savings(self):
        compared = bench.compare_paired(run(cost=None), run(cost="0.008"))
        self.assertIsNone(compared["deltaCostUsd"])
        self.assertIsNone(compared["pairedRuns"]["same-image"]["deltaCostUsd"])

    def test_unmatched_run_ids_refused(self):
        with self.assertRaisesRegex(ValueError, "exactly matching run IDs"):
            bench.compare_paired(run("old"), run("new"))

    def test_missing_comparison_provenance_refused(self):
        for field in ("reference_sha256", "render_profile_sha256", "evaluator_revision", "render_budget"):
            with self.subTest(field=field):
                changed = run()
                changed[0].pop(field)
                with self.assertRaises(ValueError):
                    bench.compare_paired(run(), changed)

    def test_mismatched_conditions_refused(self):
        mismatches = {
            "reference_sha256": "c" * 64,
            "render_profile_sha256": "d" * 64,
            "evaluator_revision": "eval-v2",
            "render_budget": 9,
        }
        for key, value in mismatches.items():
            with self.subTest(field=key):
                changed = run()
                for row in changed:
                    row[key] = value
                with self.assertRaisesRegex(ValueError, "conditions differ"):
                    bench.compare_paired(run(), changed)

    def test_inconsistent_same_run_receipts_refused(self):
        changed = run()
        changed[2]["render_budget"] = 99
        with self.assertRaisesRegex(ValueError, "inconsistent comparison conditions"):
            bench.compare_paired(run(), changed)

    def test_malformed_comparison_metadata_refused(self):
        for value in (True, 0, -1, 1.5):
            changed = run()
            changed[0]["render_budget"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "render_budget"):
                bench.compare_paired(run(), changed)
        changed = run()
        changed[0]["reference_sha256"] = "A" * 64
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            bench.compare_paired(run(), changed)

    def test_multiple_pair_deltas_and_pricing(self):
        baseline = run("one") + run("two")
        candidate = run("one", tokens=10, cost="0.008") + run("two", tokens=11, cost="0.009")
        compared = bench.compare_paired(baseline, candidate)
        self.assertEqual(compared["deltaTokens"], -12)
        self.assertEqual(compared["deltaCostUsd"], "-0.012")
        self.assertEqual(list(compared["pairedRuns"]), ["one", "two"])

    def test_cli_baseline_report_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline.jsonl"
            candidate = root / "candidate.jsonl"
            report = root / "result.json"
            baseline.write_text("\n".join(map(json.dumps, run())) + "\n", encoding="utf-8")
            candidate.write_text("\n".join(map(json.dumps, run(tokens=10))) + "\n", encoding="utf-8")
            self.assertEqual(bench.main([str(candidate), "--baseline", str(baseline), "--out", str(report)]), 0)
            first = report.read_bytes()
            self.assertEqual(bench.main([str(candidate), "--baseline", str(baseline), "--out", str(report)]), 0)
            self.assertEqual(first, report.read_bytes())
            self.assertFalse(json.loads(first)["qualityCompared"])

    def test_cli_refuses_comparison_with_missing_baseline_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline.jsonl"
            candidate = root / "candidate.jsonl"
            report = root / "result.json"
            baseline.write_text("\n".join(map(json.dumps, run("one"))) + "\n", encoding="utf-8")
            candidate.write_text("\n".join(map(json.dumps, run("two"))) + "\n", encoding="utf-8")
            self.assertEqual(bench.main([str(candidate), "--baseline", str(baseline), "--out", str(report)]), 2)
            self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
