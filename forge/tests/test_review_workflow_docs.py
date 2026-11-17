"""Keep the packaged review instructions aligned with blocking forge CLI gates."""

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ReviewWorkflowDocumentationTests(unittest.TestCase):
    def test_blockout_instructions_require_maps_off_evidence(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        render = skill.split("\n7. Render the current pass", 1)[1].split("\n8. **Run deterministic", 1)[0]
        tier1 = skill.split("\n8. **Run deterministic", 1)[1].split("\n9. Package", 1)[0]
        review = skill.split("\n10. Record the review", 1)[1].split("\n11. Sync", 1)[0]
        self.assertIn("material maps disabled", render)
        self.assertIn("--map-stripped-render", tier1)
        self.assertIn("--map-stripped-render", review)
        self.assertIn("--force-out-of-order", review)

    def test_reference_matches_review_cli_flags(self):
        scripts = (ROOT / "grimoire" / "scripts.md").read_text(encoding="utf-8")
        tier1 = scripts.split("## stage4_review/diagnose_render.py", 1)[1].split("\n## ", 1)[0]
        review = scripts.split("## stage4_review/append_review.py", 1)[1].split("\n## ", 1)[0]
        self.assertIn("--map-stripped-render", tier1)
        self.assertIn("--map-stripped-render", review)
        self.assertIn("--force-out-of-order", review)
        for script in ("diagnose_render.py", "append_review.py"):
            with self.subTest(script=script):
                command = ROOT / "forge" / "stage4_review" / script
                result = subprocess.run(
                    [sys.executable, str(command), "--help"],
                    cwd=ROOT, capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--map-stripped-render", result.stdout)
                if script == "append_review.py":
                    self.assertIn("--force-out-of-order", result.stdout)


if __name__ == "__main__":
    unittest.main()
