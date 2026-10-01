from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage4_review"))

from append_review import main as append_review_main  # noqa: E402


class DomainReviewRequiredTest(unittest.TestCase):
    def _workspace(self, profile: str) -> tuple[Path, Path]:
        root = Path(tempfile.mkdtemp(prefix="img2threejs-domain-review-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        spec = root / "spec.json"
        spec.write_text(
            json.dumps(
                {
                    "buildPasses": [{"id": "optimization-pass", "acceptance": []}],
                    "reviewHistory": [],
                }
            ),
            encoding="utf-8",
        )
        state = root / ".img2threejs" / "state.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"profile": profile}), encoding="utf-8")
        return spec, state

    def _args(self, spec: Path, action: str = "continue") -> list[str]:
        return [
            str(spec),
            "--pass-id",
            "optimization-pass",
            "--fidelity",
            "0.9",
            "--action",
            action,
            "--summary",
            "fixture review",
            "--in-place",
        ]

    def test_domain_profile_cannot_continue_without_domain_review(self) -> None:
        spec, _state = self._workspace("fixture-domain")

        with self.assertRaisesRegex(ValueError, "requires --domain-review-json"):
            append_review_main(self._args(spec))

        self.assertEqual(json.loads(spec.read_text(encoding="utf-8"))["reviewHistory"], [])

    def test_generic_profile_keeps_domain_review_optional(self) -> None:
        spec, _state = self._workspace("generic")

        self.assertEqual(append_review_main(self._args(spec)), 0)

        history = json.loads(spec.read_text(encoding="utf-8"))["reviewHistory"]
        self.assertEqual(history[-1]["action"], "continue")
        self.assertNotIn("domainReview", history[-1])

    def test_domain_profile_can_record_non_continue_action_without_report(self) -> None:
        spec, _state = self._workspace("fixture-domain")

        self.assertEqual(append_review_main(self._args(spec, "refine-code")), 0)

        history = json.loads(spec.read_text(encoding="utf-8"))["reviewHistory"]
        self.assertEqual(history[-1]["action"], "refine-code")

    def test_passing_domain_review_allows_continue(self) -> None:
        spec, _state = self._workspace("fixture-domain")
        report = spec.parent / "domain-review.json"
        report.write_text(
            json.dumps({"verdict": "pass", "failedGates": []}),
            encoding="utf-8",
        )

        args = self._args(spec)
        args.extend(["--domain-review-json", str(report)])
        self.assertEqual(append_review_main(args), 0)

        history = json.loads(spec.read_text(encoding="utf-8"))["reviewHistory"]
        self.assertEqual(history[-1]["domainReview"]["verdict"], "pass")

    def test_explicit_missing_state_fails_loud(self) -> None:
        spec, _state = self._workspace("generic")
        missing = spec.parent / "missing-state.json"

        with self.assertRaisesRegex(FileNotFoundError, "--state does not exist"):
            append_review_main(self._args(spec) + ["--state", str(missing)])


if __name__ == "__main__":
    unittest.main()
