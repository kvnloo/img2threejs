"""CLI contract for rejecting spec-review pass skips without losing state."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "_shared"))
from workflow_state import mark_steps, new_state, set_current_pass  # noqa: E402


class PassSyncCliErrorTest(unittest.TestCase):
    def _execute(self, spec, prepare=None):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            spec_path = Path(directory) / "spec.json"
            state = new_state("reference.png", spec=str(spec_path))
            if prepare is not None:
                prepare(state)
            state_path.write_text(json.dumps(state), encoding="utf-8")
            before = state_path.read_bytes()
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "next.py"), "--state", str(state_path)],
                capture_output=True, text=True,
            )
            after = state_path.read_bytes()
            return result, before, after

    def test_imported_review_cannot_skip_first_pass_without_traceback(self):
        # optimization-pass is deliberately nonvisual: a 'continue' review
        # reaches current_pass() without fabricating any screenshot evidence.
        spec = {
            "buildPasses": [{"id": "optimization-pass"}, {"id": "blockout"}],
            "reviewHistory": [{"passId": "optimization-pass", "action": "continue"}],
        }
        result, before, after = self._execute(spec)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("state error:", result.stderr)
        self.assertIn("has not opened the first pass", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(after, before)

    def test_two_reviewed_passes_cannot_consume_one_local_checklist(self):
        def prepare(state):
            setup = [row["id"] for row in state["checklist"] if row["scope"] == "setup"]
            steps = [row["id"] for row in state["checklist"] if row["scope"] == "pass"]
            mark_steps(state, setup, status="done", evidence=["setup.json"])
            set_current_pass(state, "calibration-pass")
            mark_steps(state, steps, status="done", evidence=["pass.json"])

        spec = {
            "buildPasses": [
                {"id": "calibration-pass"}, {"id": "optimization-pass"}, {"id": "final-pass"}
            ],
            "reviewHistory": [
                {"passId": "calibration-pass", "action": "continue"},
                {"passId": "optimization-pass", "action": "continue"},
            ],
        }
        result, before, after = self._execute(spec, prepare)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("state error:", result.stderr)
        self.assertIn("skipped pass boundary", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(after, before)

    def test_valid_initial_pass_still_advances_normally(self):
        spec = {"buildPasses": [{"id": "blockout"}], "reviewHistory": []}
        result, before, after = self._execute(spec)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(after, before)
        self.assertIn("pass=blockout", result.stdout)


if __name__ == "__main__":
    unittest.main()
