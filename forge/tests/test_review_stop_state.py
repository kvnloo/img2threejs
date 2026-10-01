from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "_shared"))

from workflow_state import new_state, status_payload, sync_from_spec  # noqa: E402


class ReviewStopStateTest(unittest.TestCase):
    def test_stop_review_hard_stops_local_state(self) -> None:
        state = new_state("reference.png")
        spec = {"reviewHistory": [{"passId": "blockout", "action": "stop"}]}

        sync_from_spec(state, spec, "blockout")

        payload = status_payload(state)
        self.assertEqual(payload["status"], "stopped")
        self.assertEqual(payload["currentStep"], "stopped")
        self.assertEqual(payload["stopReason"], "review-action-stop:blockout")
        self.assertIsNone(payload["nextCommand"])

    def test_stop_review_is_recovered_even_when_cursor_already_advanced(self) -> None:
        state = new_state("reference.png")
        state["reviewCursor"] = 1
        spec = {"reviewHistory": [{"passId": "blockout", "action": "stop"}]}

        sync_from_spec(state, spec, "blockout")

        self.assertEqual(status_payload(state)["stopReason"], "review-action-stop:blockout")

    def test_next_cli_returns_stopped_exit_code_after_stop_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.json"
            spec_path = root / "spec.json"
            state = new_state("reference.png", spec=str(spec_path))
            state_path.write_text(json.dumps(state), encoding="utf-8")
            spec_path.write_text(
                json.dumps(
                    {
                        "buildPasses": [{"id": "blockout", "acceptance": []}],
                        "reviewHistory": [{"passId": "blockout", "action": "stop"}],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "forge" / "next.py"),
                    str(spec_path),
                    "--state",
                    str(state_path),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertIn("LOCAL_STATE status=stopped step=stopped pass=blockout", result.stdout)
            self.assertIn("STOP: review-action-stop:blockout", result.stdout)
            self.assertNotIn("await-pass-transition", result.stdout)


if __name__ == "__main__":
    unittest.main()
