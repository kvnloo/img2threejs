"""Regressions for the domain-review attachment bypass (upstream #122)."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stage4_review"))
sys.path.insert(0, str(ROOT / "_shared"))

from append_review import main as append_review_main  # noqa: E402
from workflow_state import new_state, save_state, WorkflowStateError  # noqa: E402


def available_domain(profile: str):
    return {} if profile == "fixture-domain" else None


class DomainReviewAttachmentTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.work = self.root / "work"
        self.work.mkdir()
        self.cwd = self.root / "cwd"
        self.cwd.mkdir()
        self.spec = self.work / "object-sculpt-spec.json"
        self.spec.write_text(json.dumps({
            "buildPasses": [{"id": "optimization-pass"}],
            "reviewHistory": [],
        }) + "\n", encoding="utf-8")

    def write_state(self, profile="fixture-domain", path=None):
        path = path or self.work / ".img2threejs" / "state.json"
        with patch("workflow_state.domain_profile", side_effect=available_domain):
            save_state(path, new_state("reference.png", profile=profile, spec=str(self.spec)))
        return path

    def run_review(self, action="continue", *extra):
        argv = [
            str(self.spec), "--pass-id", "optimization-pass", "--fidelity", "0.8",
            "--action", action, "--summary", "domain review regression", "--in-place",
            *extra,
        ]
        with (
            patch("workflow_state.domain_profile", side_effect=available_domain),
            patch("append_review.Path.cwd", return_value=self.cwd),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return append_review_main(argv)

    def test_legacy_stateless_continue_remains_supported(self):
        self.assertEqual(self.run_review(), 0)

    def test_generic_profile_does_not_require_domain_report(self):
        self.write_state("generic")
        self.assertEqual(self.run_review(), 0)

    def test_domain_profile_refuses_missing_report_without_mutating_spec(self):
        self.write_state()
        before = self.spec.read_bytes()
        with self.assertRaisesRegex(ValueError, "requires --domain-review-json"):
            self.run_review()
        self.assertEqual(self.spec.read_bytes(), before)

    def test_null_report_cannot_bypass_mandatory_attachment(self):
        self.write_state()
        with self.assertRaisesRegex(ValueError, "requires --domain-review-json"):
            self.run_review("continue", "--domain-review-json", "null")

    def test_passing_domain_report_allows_continue_and_records_receipt(self):
        self.write_state()
        self.assertEqual(self.run_review("continue", "--domain-review-json", '{"verdict":"pass"}'), 0)
        history = json.loads(self.spec.read_text(encoding="utf-8"))["reviewHistory"]
        self.assertEqual(history[0]["domainReview"]["verdict"], "pass")
        self.assertEqual(history[0]["cs2Review"]["verdict"], "pass")

    def test_nonpassing_domain_report_still_blocks_continue(self):
        self.write_state()
        before = self.spec.read_bytes()
        with self.assertRaisesRegex(ValueError, "blocking continuation"):
            self.run_review("continue", "--domain-review-json", '{"verdict":"reject","failedGates":["domain"]}')
        self.assertEqual(self.spec.read_bytes(), before)

    def test_noncontinue_actions_remain_available_without_domain_evidence(self):
        for action in ("refine-spec", "refine-code", "request-input", "stop"):
            with self.subTest(action=action):
                self.spec.write_text(json.dumps({"buildPasses": [{"id": "optimization-pass"}], "reviewHistory": []}))
                self.write_state()
                self.assertEqual(self.run_review(action), 0)
                history = json.loads(self.spec.read_text())["reviewHistory"]
                self.assertEqual(history[0]["action"], action)

    def test_cwd_discovery_when_spec_folder_has_no_state(self):
        self.write_state(path=self.cwd / ".img2threejs" / "state.json")
        with self.assertRaisesRegex(ValueError, "requires --domain-review-json"):
            self.run_review()

    def test_spec_local_state_takes_precedence_over_cwd_state(self):
        self.write_state("fixture-domain")
        self.write_state("generic", path=self.cwd / ".img2threejs" / "state.json")
        with self.assertRaisesRegex(ValueError, "requires --domain-review-json"):
            self.run_review()

    def test_explicit_state_overrides_discovered_generic_state(self):
        self.write_state("generic")
        specified = self.write_state("fixture-domain", path=self.root / "another-workflow.json")
        with self.assertRaisesRegex(ValueError, "requires --domain-review-json"):
            self.run_review("continue", "--state", str(specified))

    def test_explicit_missing_state_fails_loud(self):
        with self.assertRaisesRegex(WorkflowStateError, "does not exist"):
            self.run_review("continue", "--state", str(self.root / "absent.json"))

    def test_explicit_malformed_state_fails_loud(self):
        bad = self.root / "invalid.json"
        bad.write_text("{")
        with self.assertRaisesRegex(WorkflowStateError, "not valid JSON"):
            self.run_review("continue", "--state", str(bad))

    def test_implicit_malformed_state_fails_loud(self):
        bad = self.work / ".img2threejs" / "state.json"
        bad.parent.mkdir()
        bad.write_text("{")
        with self.assertRaisesRegex(WorkflowStateError, "not valid JSON"):
            self.run_review()

    def test_legacy_alias_still_records_domain_review(self):
        self.write_state()
        self.assertEqual(self.run_review("continue", "--cs2-review-json", '{"verdict":"pass"}'), 0)


if __name__ == "__main__":
    unittest.main()
