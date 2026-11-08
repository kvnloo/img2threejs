from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NEXT = ROOT / "forge" / "next.py"
STATE = ROOT / "forge" / "state.py"


class NextSpecRootTypeTest(unittest.TestCase):
    def test_non_object_json_roots_fail_cleanly(self):
        for payload in ([], "scalar", None, 42):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                spec_path = Path(directory) / "bad.json"
                spec_path.write_text(json.dumps(payload), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(NEXT), str(spec_path)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("spec error: spec must be an object", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_non_object_spec_does_not_mutate_local_state(self):
        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "bad.json"
            state_path = Path(directory) / "state.json"
            spec_path.write_text("[]", encoding="utf-8")
            init = subprocess.run(
                [sys.executable, str(STATE), "init", "--state", str(state_path),
                 "--reference", "reference.png", "--spec", str(spec_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            before = state_path.read_bytes()
            result = subprocess.run(
                [sys.executable, str(NEXT), "--state", str(state_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("spec error: spec must be an object", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(state_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
