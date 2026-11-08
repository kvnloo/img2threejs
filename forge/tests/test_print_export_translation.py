"""Signed-volume regressions for shells far from the world origin.

A watertight object must have the same signed volume regardless of placement;
the sign is also used to reject inside-out printable exports.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage3_build"))

import print_export  # noqa: E402


FACES = [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]
ORIGIN_POINTS = [[0, 0, 0], [2, 0, 0], [0, 3, 0], [0, 0, 4]]


def tetra(shift=(0, 0, 0), *, inverted=False):
    return {
        "name": "tetra",
        "vertices": [[point[i] + shift[i] for i in range(3)] for point in ORIGIN_POINTS],
        "indices": [[a, c, b] for a, b, c in FACES] if inverted else FACES,
    }


class TranslationInvariantSignedVolume(unittest.TestCase):
    def test_small_tetra_volume_is_translation_invariant(self):
        # The former world-origin triple product can report 2.3e9 instead of
        # 4 at +1e9, or a negative volume at +1e12.
        for offset in (0, 1e9, -1e9, 1e12):
            with self.subTest(offset=offset):
                mesh = tetra((offset, offset, offset))
                report = print_export.build_export([mesh])["report"]
                self.assertTrue(report["watertight"])
                self.assertAlmostEqual(report["volume"], 4.0, places=7)
                self.assertEqual(report["insideOutShellCount"], 0)

    def test_inverted_tetra_is_rejected_at_large_coordinates(self):
        for offset in (0, 1e9, -1e9, 1e12):
            with self.subTest(offset=offset):
                mesh = tetra((offset, offset, offset), inverted=True)
                report = print_export.build_export([mesh])["report"]
                self.assertTrue(report["watertight"])
                self.assertAlmostEqual(report["volume"], -4.0, places=7)
                self.assertEqual(report["insideOutShellCount"], 1)

    def test_two_distant_closed_shells_have_additive_volumes(self):
        meshes = [
            tetra((1e9, 1e9, 1e9)),
            tetra((-1e9, -1e9, -1e9)),
        ]
        report = print_export.build_export(meshes)["report"]
        self.assertTrue(report["watertight"])
        self.assertEqual(report["shellCount"], 2)
        self.assertAlmostEqual(report["volume"], 8.0, places=7)
        self.assertEqual(report["insideOutShellCount"], 0)


if __name__ == "__main__":
    unittest.main()
