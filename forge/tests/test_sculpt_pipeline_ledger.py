from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stage2_spec"))

from validate_sculpt_spec import validate_sculpt_pipeline  # noqa: E402


class SculptPipelineLedgerTest(unittest.TestCase):
    def test_stale_completed_passes_is_a_strict_quality_warning(self) -> None:
        spec = {
            "reviewHistory": [],
            "sculptPipeline": {
                "passGateMode": "locked-sequential",
                "passOrder": ["blockout"],
                "currentPass": "blockout",
                "completedPasses": ["blockout"],
                "nextRequiredEvidence": [],
            },
        }
        errors: list[str] = []
        warnings: list[str] = []
        validate_sculpt_pipeline(spec, ["blockout"], errors, warnings)

        self.assertEqual(errors, [])
        self.assertIn(
            "quality: sculptPipeline.completedPasses is out of sync with reviewHistory; "
            "run stage3_build/orchestrate_passes.py sync",
            warnings,
        )


if __name__ == "__main__":
    unittest.main()
