"""Keep the mandatory mesh-export command in SKILL.md resolvable and tested."""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "runtime" / "scripts" / "export_mesh_geometry.mjs"
TEST = ROOT / "runtime" / "scripts" / "export_mesh_geometry.test.mjs"


class MeshExportScriptTest(unittest.TestCase):
    def test_documented_command_exists(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("node runtime/scripts/export_mesh_geometry.mjs", skill)
        self.assertTrue(SCRIPT.is_file(), "SKILL.md references a missing mandatory exporter")
        self.assertTrue(TEST.is_file(), "mesh exporter must keep its regression suite")

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_node_extraction_contract(self) -> None:
        result = subprocess.run(
            ["node", "--test", str(TEST)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)


if __name__ == "__main__":
    unittest.main()
