from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stage1_intake"))

from material_region_analysis import _safe_filename_component  # noqa: E402


class MaterialRegionPathSafetyTest(unittest.TestCase):
    def test_region_id_cannot_create_path_components(self) -> None:
        for raw in (
            "../../outside",
            r"..\..\outside",
            "/absolute/path",
            r"C:\temp\paint",
            "paint / .. \\ coat",
        ):
            with self.subTest(region_id=raw):
                safe = _safe_filename_component(raw)
                self.assertTrue(safe)
                self.assertNotIn("/", safe)
                self.assertNotIn("\\", safe)
                self.assertNotEqual(safe, ".")
                self.assertNotEqual(safe, "..")

                root = Path("/tmp/material-output").resolve()
                candidate = (root / f"00-{safe}.png").resolve()
                self.assertEqual(candidate.parent, root)

    def test_normal_region_id_stays_readable(self) -> None:
        self.assertEqual(_safe_filename_component("paint-main_02"), "paint-main_02")


if __name__ == "__main__":
    unittest.main()
