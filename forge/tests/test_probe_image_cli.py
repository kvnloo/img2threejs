"""probe_image.py must reject a directory argument with a clean usage error.

Before this guard, `probe_image.py <dir>` passed the `exists()` check and then crashed in
`path.read_bytes()` with an uncaught IsADirectoryError traceback (exit 1), while a missing
path already exited 2 through argparse. Pure stdlib; runs the CLI as a subprocess.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "stage1_intake" / "probe_image.py"


def run_probe(target):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(target)],
        capture_output=True,
        text=True,
        timeout=60,
    )


class ProbeImageCliTest(unittest.TestCase):
    def test_directory_argument_is_a_usage_error_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_probe(tmp)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("is not a file", r.stderr)

    def test_missing_path_still_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_probe(Path(tmp) / "absent.png")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("does not exist", r.stderr)


if __name__ == "__main__":
    unittest.main()
