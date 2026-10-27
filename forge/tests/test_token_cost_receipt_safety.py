#!/usr/bin/env python3
"""Measured provider-usage inputs cannot be overwritten by report publication."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import benchmark_token_cost as bench  # noqa: E402


def measured(run="a"):
    rows = []
    for index, stage in enumerate(sorted(bench.REQUIRED)):
        rows.append({
            "run_id": run, "event_id": f"call-{index}", "stage": stage,
            "model": "test-model", "provider": "test-provider",
            "usage_source": "provider",
            "usage": {
                "prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12,
            },
            "reference_sha256": "a" * 64, "render_profile_sha256": "b" * 64,
            "evaluator_revision": "eval-v1", "render_budget": 4,
        })
    return rows


class ReceiptSafety(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.candidate = self.root / "candidate.jsonl"
        self.baseline = self.root / "baseline.jsonl"
        self.candidate.write_text(
            "\n".join(json.dumps(row) for row in measured()) + "\n", encoding="utf-8"
        )
        self.baseline.write_text(
            "\n".join(json.dumps(row) for row in measured()) + "\n", encoding="utf-8"
        )
        self.out = self.root / "receipt.json"

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = bench.main([str(a) for a in args])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_output_cannot_alias_candidate_even_with_relative_path(self):
        old = self.candidate.read_bytes()
        status, _, err = self.run_cli(
            self.candidate, "--out", self.root / "subdir" / ".." / "candidate.jsonl"
        )
        self.assertEqual(status, 2)
        self.assertIn("--out must differ", err)
        self.assertEqual(self.candidate.read_bytes(), old)
        self.assertFalse((self.root / "subdir").exists())

    def test_output_symlink_to_input_is_refused_without_truncating_source(self):
        alias = self.root / "alias.json"
        try:
            alias.symlink_to(self.candidate)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        old = self.candidate.read_bytes()
        status, _, err = self.run_cli(self.candidate, "--out", alias)
        self.assertEqual(status, 2, err)
        self.assertEqual(self.candidate.read_bytes(), old)

    def test_output_cannot_overwrite_paired_baseline(self):
        old = self.baseline.read_bytes()
        status, _, err = self.run_cli(
            self.candidate, "--baseline", self.baseline, "--out", self.baseline
        )
        self.assertEqual(status, 2, err)
        self.assertIn("--out must differ", err)
        self.assertEqual(self.baseline.read_bytes(), old)

    def test_nonobject_jsonl_is_controlled_error_and_keeps_previous_report(self):
        prior = b'{"previous":true}\n'
        self.out.write_bytes(prior)
        for value in (None, [], True, "not-an-event", 42):
            with self.subTest(value=value):
                self.candidate.write_text(json.dumps(value) + "\n", encoding="utf-8")
                status, _, err = self.run_cli(self.candidate, "--out", self.out)
                self.assertEqual(status, 2)
                self.assertIn("expected a JSON object", err)
                self.assertEqual(self.out.read_bytes(), prior)

    def test_atomic_publication_preserves_existing_receipt_on_write_failure(self):
        old = b'{"verified":true}\n'
        self.out.write_bytes(old)
        with patch.object(bench.os, "replace", side_effect=OSError("disk unavailable")):
            status, _, err = self.run_cli(self.candidate, "--out", self.out)
        self.assertEqual(status, 2)
        self.assertIn("disk unavailable", err)
        self.assertEqual(self.out.read_bytes(), old)
        self.assertEqual(list(self.root.glob(".receipt.json.*.tmp")), [])

    def test_atomic_publication_does_not_leave_partial_new_report(self):
        with patch.object(bench.os, "replace", side_effect=OSError("publish denied")):
            status, _, _ = self.run_cli(self.candidate, "--out", self.out)
        self.assertEqual(status, 2)
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.root.glob(".receipt.json.*.tmp")), [])

    def test_paired_success_writes_valid_complete_report_without_temp_file(self):
        status, _, err = self.run_cli(
            self.candidate, "--baseline", self.baseline, "--out", self.out
        )
        self.assertEqual(status, 0, err)
        data = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertFalse(data["qualityCompared"])
        self.assertEqual(data["pairedRuns"]["a"]["deltaTokens"], 0)
        self.assertEqual(list(self.root.glob(".receipt.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
