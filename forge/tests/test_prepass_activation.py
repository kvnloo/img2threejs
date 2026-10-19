"""Regression coverage for inactive pass rows before the first pass opens (issue #123)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "_shared"))

from workflow_state import (  # noqa: E402
    WorkflowStateError,
    mark_steps,
    new_state,
    set_current_pass,
    status_payload,
)


class PrepassActivationTest(unittest.TestCase):
    def _finish_setup(self, state: dict) -> None:
        setup = [row["id"] for row in state["checklist"] if row["scope"] == "setup"]
        mark_steps(state, setup, status="done", evidence=["setup.json"])

    def test_no_pass_rows_are_offered_at_init(self):
        state = new_state("reference.png", spec="spec.json")
        payload = status_payload(state)
        self.assertEqual(payload["currentStep"], "image-analysis")
        self.assertNotIn("build-current-pass", payload["pending"])

    def test_completed_setup_cannot_mark_pass_work_before_a_pass_opens(self):
        state = new_state("reference.png", spec="spec.json")
        self._finish_setup(state)
        payload = status_payload(state)
        self.assertEqual(payload["currentPass"], "")
        self.assertEqual(payload["currentStep"], "await-pass-start")
        self.assertNotIn("build-current-pass", payload["pending"])
        self.assertNotIn("generate_threejs_factory.py", payload["nextCommand"])
        with self.assertRaisesRegex(WorkflowStateError, "out-of-order"):
            mark_steps(state, ["build-current-pass"], status="done", evidence=["premature.ts"])
        self.assertEqual(state["currentPass"], "")
        set_current_pass(state, "blockout")
        payload = status_payload(state)
        self.assertEqual(payload["currentStep"], "build-current-pass")
        self.assertIn("build-current-pass", payload["pending"])
        self.assertIn("--pass-id blockout", payload["nextCommand"])

    def test_next_cli_waits_for_spec_without_offering_pass_work(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            spec_path = Path(directory) / "not-yet-authored.json"
            state = new_state("reference.png", spec=str(spec_path))
            self._finish_setup(state)
            state_path.write_text(json.dumps(state), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "next.py"), "--state", str(state_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("step=await-pass-start pass=none", result.stdout)
            self.assertNotIn("generate_threejs_factory.py", result.stdout)
            self.assertNotIn("- build-current-pass", result.stdout)


if __name__ == "__main__":
    unittest.main()
