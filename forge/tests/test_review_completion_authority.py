#!/usr/bin/env python3
"""Cross-stage regression: an incomplete review can never unlock code generation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

FORGE = Path(__file__).resolve().parents[1]
for directory in (FORGE / "_shared", FORGE / "stage2_spec", FORGE / "stage3_build", FORGE / "stage4_review"):
    sys.path.insert(0, str(directory))

import review_completion as policy
import append_review as reviewer
import generate_threejs_factory as generator
import orchestrate_passes as orchestrator
import validate_sculpt_spec as validator


class ReviewCompletionAuthorityTest(unittest.TestCase):
    def setUp(self):
        self.good = {
            "passId": "blockout",
            "action": "continue",
            "mapStrippedRender": "unlit.png",
            "visualEvidence": {"renderScreenshot": "render.png", "comparisonImage": "side-by-side.png"},
            "aiVisionScore": 0.91,
            "visualAcceptanceThreshold": 0.7,
            "reviewViewpoints": ["thickness-axis", "long-axis"],
        }

    def spec(self, entry):
        return {"reviewHistory": [entry], "buildPasses": [{"id": "blockout"}, {"id": "structural-pass"}]}

    def assert_all_consumers(self, entry, expected):
        spec = self.spec(entry)
        self.assertEqual(policy.review_completes_pass(spec, entry, "blockout"), expected)
        self.assertEqual(reviewer.review_completes_pass(spec, entry, "blockout"), expected)
        self.assertEqual(orchestrator.review_completes_pass(spec, entry, "blockout"), expected)
        self.assertEqual(validator.review_completes_pass(spec, entry, "blockout"), expected)
        credited = ["blockout"] if expected else []
        self.assertEqual(generator.completed_passes(spec, ["blockout", "structural-pass"]), credited)
        self.assertEqual(orchestrator.completed_passes(spec, ["blockout", "structural-pass"]), credited)
        self.assertEqual(validator.completed_passes_from_history(spec, ["blockout", "structural-pass"]), credited)
        if expected:
            generator.assert_pass_unlocked(spec, "structural-pass")
        else:
            with self.assertRaises(ValueError):
                generator.assert_pass_unlocked(spec, "structural-pass")

    def test_all_stages_import_one_predicate(self):
        for module in (reviewer, orchestrator, validator, generator):
            self.assertIs(module.review_completes_pass, policy.review_completes_pass)

    def test_complete_review_credits_blockout(self):
        self.assert_all_consumers(dict(self.good), True)

    def test_missing_map_stripped_render_blocks(self):
        entry = dict(self.good)
        entry.pop("mapStrippedRender")
        self.assert_all_consumers(entry, False)

    def test_missing_comparison_blocks(self):
        entry = dict(self.good)
        entry["visualEvidence"] = {"renderScreenshot": "render.png"}
        self.assert_all_consumers(entry, False)

    def test_missing_score_blocks(self):
        entry = dict(self.good)
        entry.pop("aiVisionScore")
        self.assert_all_consumers(entry, False)

    def test_subthreshold_score_blocks(self):
        entry = dict(self.good, aiVisionScore=0.3)
        self.assert_all_consumers(entry, False)

    def test_invalid_numeric_scores_fail_closed(self):
        for score in (True, float("nan"), float("inf"), float("-inf")):
            with self.subTest(score=score):
                self.assert_all_consumers(dict(self.good, aiVisionScore=score), False)

    def test_incomplete_viewpoints_block(self):
        self.assert_all_consumers(dict(self.good, reviewViewpoints=["long-axis"]), False)

    def test_non_continue_review_cannot_unlock(self):
        self.assert_all_consumers(dict(self.good, action="refine-code"), False)

    def test_nonvisual_pass_does_not_require_visual_evidence(self):
        entry = {"passId": "optimization-pass", "action": "continue"}
        self.assertTrue(policy.review_completes_pass({"reviewHistory": [entry]}, entry, "optimization-pass"))


if __name__ == "__main__":
    unittest.main()
