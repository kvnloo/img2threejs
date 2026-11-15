#!/usr/bin/env python3
"""Cleanup-safe showcase TypeScript smoke coverage for primitive-only factories."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if __package__:
    from .showcase_test_support import showcase_root
else:
    from showcase_test_support import showcase_root

SKILL_ROOT = Path(__file__).resolve().parents[2]
IMPLICIT_FIXTURE = SKILL_ROOT / "forge" / "tests" / "fixtures" / "implicit_character_torso_limb.json"
VISUAL_HULL_FIXTURE = SKILL_ROOT / "forge" / "tests" / "fixtures" / "visual_hull_two_views.json"


def run(script: str, *args: object) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SKILL_ROOT / "forge" / script), *map(str, args)]
    if script == "stage3_build/generate_threejs_factory.py" and "--pass-id" not in args:
        command.append("--allow-nonstrict")
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
    )


class ShowcaseTscSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.showcase_root = showcase_root()
        self.showcase_source = self.showcase_root / "src" / "__geometry_engine_smoke__.ts"
        self.showcase_failure_source = self.showcase_root / "src" / "__geometry_engine_smoke_failure__.ts"

    def _generate_primitive_only_factory(self, out: Path) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "oak.json"
            spec_result = run("stage2_spec/new_sculpt_spec.py", "Oak", "--out", spec_path)
            self.assertEqual(spec_result.returncode, 0, spec_result.stderr)

            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            self.assertEqual(spec["componentTree"][0]["primitive"], "box")

            generate_result = run("stage3_build/generate_threejs_factory.py", spec_path, "--out", out)
            self.assertEqual(generate_result.returncode, 0, generate_result.stderr)

    def _run_tsc(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["npx", "tsc", "--noEmit"],
            cwd=self.showcase_root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_showcase_smoke_source_is_removed_after_tsc_success_and_failure(self) -> None:
        for should_fail in (False, True):
            with self.subTest(compiler_failure=should_fail):
                self.assertFalse(self.showcase_source.exists())
                self.assertFalse(self.showcase_failure_source.exists())
                try:
                    self._generate_primitive_only_factory(self.showcase_source)
                    self.assertTrue(self.showcase_source.exists())

                    if should_fail:
                        self.showcase_failure_source.write_text(
                            "export const broken: string = 1;\n",
                            encoding="utf-8",
                        )

                    tsc_result = self._run_tsc()
                    if should_fail:
                        self.assertNotEqual(tsc_result.returncode, 0, tsc_result.stderr)
                    else:
                        self.assertEqual(tsc_result.returncode, 0, tsc_result.stderr)
                finally:
                    if self.showcase_source.exists():
                        self.showcase_source.unlink()
                    if self.showcase_failure_source.exists():
                        self.showcase_failure_source.unlink()

                self.assertFalse(self.showcase_source.exists())
                self.assertFalse(self.showcase_failure_source.exists())

    def test_implicit_sdf_factory_typechecks_and_is_removed(self) -> None:
        self.assertFalse(self.showcase_source.exists())
        try:
            generate_result = run("stage3_build/generate_threejs_factory.py", IMPLICIT_FIXTURE, "--out", self.showcase_source)
            self.assertEqual(generate_result.returncode, 0, generate_result.stderr)
            self.assertEqual(self._run_tsc().returncode, 0)
        finally:
            if self.showcase_source.exists():
                self.showcase_source.unlink()

        self.assertFalse(self.showcase_source.exists())

    def test_visual_hull_factory_typechecks_and_is_removed(self) -> None:
        self.assertFalse(self.showcase_source.exists())
        try:
            generate_result = run("stage3_build/generate_threejs_factory.py", VISUAL_HULL_FIXTURE, "--out", self.showcase_source)
            self.assertEqual(generate_result.returncode, 0, generate_result.stderr)
            self.assertEqual(self._run_tsc().returncode, 0)
        finally:
            if self.showcase_source.exists():
                self.showcase_source.unlink()

        self.assertFalse(self.showcase_source.exists())



class ThreeRtTscSmokeTest(unittest.TestCase):
    """Compile the real emitted module against the real ThreeRT source, not a declaration stub."""

    def test_threert_generated_factory_typechecks_without_threejs(self) -> None:
        configured = os.environ.get("IMG2THREEJS_THREERT_ROOT")
        if not configured:
            message = "set IMG2THREEJS_THREERT_ROOT to a ThreeRT checkout with npm dependencies"
            if os.environ.get("IMG2THREEJS_REQUIRE_THREERT") == "1":
                self.fail(message)
            self.skipTest(message)
        root = Path(configured).expanduser().resolve()
        package = root / "packages" / "scene"
        tsc = root / "node_modules" / ".bin" / "tsc"
        self.assertTrue((package / "package.json").is_file(), "ThreeRT scene package required")
        self.assertTrue(tsc.is_file(), "ThreeRT node_modules/.bin/tsc required")

        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            output = work / "src" / "createThreeRtStaticBox.ts"
            output.parent.mkdir(parents=True)
            fixture = SKILL_ROOT / "forge/tests/fixtures/threert_static_box.json"
            generated = run("stage3_build/generate_threejs_factory.py",
                            fixture, "--backend", "threert", "--out", output)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            source = output.read_text(encoding="utf-8")
            self.assertIn("from '@threert/scene'", source)
            self.assertNotIn("from 'three'", source)
            self.assertNotIn("three/examples", source)

            scope = work / "node_modules" / "@threert"
            scope.mkdir(parents=True)
            (scope / "scene").symlink_to(package, target_is_directory=True)
            self.assertFalse((work / "node_modules" / "three").exists())
            config = {
                "compilerOptions": {
                    "target": "es2023",
                    "module": "esnext",
                    "moduleResolution": "bundler",
                    "lib": ["es2023"],
                    "strict": True,
                    "noEmit": True,
                    "skipLibCheck": True,
                    "allowImportingTsExtensions": True,
                    "verbatimModuleSyntax": True,
                    "erasableSyntaxOnly": True,
                    "isolatedModules": True,
                    "types": ["node"],
                    "typeRoots": [str(root / "node_modules" / "@types")],
                },
                "files": [str(output)],
            }
            tsconfig = work / "tsconfig.json"
            tsconfig.write_text(json.dumps(config, indent=2), encoding="utf-8")
            checked = subprocess.run([str(tsc), "-p", str(tsconfig)], cwd=work,
                                     capture_output=True, text=True, check=False)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
