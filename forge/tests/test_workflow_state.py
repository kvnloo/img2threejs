from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "_shared"))

from state_integrity import write_state  # noqa: E402
from workflow_state import (  # noqa: E402
    WorkflowStateError,
    load_state,
    mark_steps,
    new_state,
    set_current_pass,
    status_payload,
    sync_from_spec,
)


class WorkflowStateTest(unittest.TestCase):
    def test_generic_state_starts_with_mandatory_image_analysis(self):
        state = new_state("reference.png")
        payload = status_payload(state)
        self.assertEqual(payload["currentStep"], "image-analysis")
        self.assertEqual(payload["loop"]["passCount"], 0)
        self.assertEqual(payload["loop"]["maxPerPass"], 3)
        self.assertIn("part-coverage", payload["pending"])
        ids = [entry["id"] for entry in state["checklist"]]
        self.assertLess(ids.index("reference-suitability"), ids.index("reference-admission"))
        self.assertLess(ids.index("detail-inventory"), ids.index("projection-route"))
        self.assertLess(ids.index("projection-route"), ids.index("spec-authoring"))
        self.assertLess(ids.index("material-evidence"), ids.index("strict-validation"))

    def test_material_reference_wiring_is_in_the_setup_checklist(self):
        """The material track is executable, not prose.

        Both steps were dropped once already: merge 7214452 resolved this file to a revision
        whose `material-evidence` step only *described* running a script, and which had no
        wiring step at all, so `material_region_analysis.py` and `apply_material_analysis.py`
        became unreachable from the checklist that drives the pipeline. This test is what makes
        that regression fail loudly instead of silently.
        """
        state = new_state("reference.png")
        by_id = {entry["id"]: entry for entry in state["checklist"]}
        self.assertIn("material-evidence", by_id)
        self.assertIn("material-spec-wiring", by_id)
        self.assertIn("material_region_analysis.py", by_id["material-evidence"]["command"])
        self.assertIn("apply_material_analysis.py", by_id["material-spec-wiring"]["command"])
        ids = [entry["id"] for entry in state["checklist"]]
        self.assertLess(ids.index("spec-authoring"), ids.index("material-evidence"))
        self.assertLess(ids.index("material-evidence"), ids.index("material-spec-wiring"))
        self.assertLess(ids.index("material-spec-wiring"), ids.index("strict-validation"))

    def test_plugin_domain_steps_splice_before_their_anchors(self):
        """A plugin-contributed domain drives the checklist through the registry, hermetically.

        This test used to build a `cs2` state and passed only on machines where the cs2 plugin
        happened to be installed under ~/.img2 -- the machine-global dependency that turned CI
        red. It now installs a fixture plugin (mirroring cs2's `domain.json` shape: setup steps
        anchored before `local-spec-search`, one pass step anchored before `ai-review-recorded`)
        into a disposable $IMG2_HOME and asserts the same splice-order semantics.
        """
        domain_entry = {
            "id": "fixture-dom",
            "setupSteps": [
                ["fx-contract-read", "Read {plugin_dir}/grimoire/contract.md completely"],
                ["fx-classification", "Obtain an authoritative fixture classification record"],
                ["fx-manifest", "python3 {plugin_dir}/tools/manifest.py {reference} --out fx.json"],
            ],
            "setupAnchorBefore": "local-spec-search",
            "passSteps": [
                ["fx-review", "python3 {plugin_dir}/tools/review.py --spec {spec} --out fx-review.json"]
            ],
            "passAnchorBefore": "ai-review-recorded",
        }
        home = Path(tempfile.mkdtemp(prefix="img2-home-"))
        self.addCleanup(shutil.rmtree, home, True)
        plugin_dir = home / "plugins" / "fixture-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "domain.json").write_text(json.dumps(domain_entry), encoding="utf-8")
        (home / "plugins.json").write_text(
            json.dumps({"version": 1, "plugins": [{"id": "fixture-plugin"}]}), encoding="utf-8"
        )
        prior = os.environ.get("IMG2_HOME")
        os.environ["IMG2_HOME"] = str(home)
        try:
            state = new_state("fixture.png", profile="fixture-dom")
        finally:
            if prior is None:
                os.environ.pop("IMG2_HOME", None)
            else:
                os.environ["IMG2_HOME"] = prior
        ids = [entry["id"] for entry in state["checklist"]]
        self.assertLess(ids.index("fx-contract-read"), ids.index("fx-classification"))
        self.assertLess(ids.index("fx-classification"), ids.index("fx-manifest"))
        self.assertLess(ids.index("fx-manifest"), ids.index("local-spec-search"))
        self.assertLess(ids.index("local-spec-search"), ids.index("pre-spec-assessment"))
        self.assertLess(ids.index("pass-gate-check"), ids.index("fx-review"))
        self.assertLess(ids.index("fx-review"), ids.index("ai-review-recorded"))
        by_id = {entry["id"]: entry for entry in state["checklist"]}
        self.assertIn(str(plugin_dir), by_id["fx-manifest"]["command"])

    def test_character_state_requires_contract_landmarks_and_route_decision(self):
        state = new_state("character.png", profile="character")
        ids = [entry["id"] for entry in state["checklist"]]
        self.assertLess(ids.index("character-contract-read"), ids.index("character-landmarks"))
        self.assertLess(ids.index("character-landmarks"), ids.index("pre-spec-assessment"))
        self.assertLess(ids.index("character-landmarks"), ids.index("projection-route"))

    def test_pass_commands_follow_executable_gate_order(self):
        state = new_state("reference.png", spec="spec.json")
        entries = [entry for entry in state["checklist"] if entry["scope"] == "pass"]
        ids = [entry["id"] for entry in entries]
        commands = {entry["id"]: entry["command"] for entry in entries}
        self.assertIn("generate_threejs_factory.py", commands["build-current-pass"])
        self.assertLess(ids.index("build-current-pass"), ids.index("tier1-diagnostics"))
        self.assertLess(ids.index("tier1-diagnostics"), ids.index("pass-gate-check"))
        self.assertLess(ids.index("pass-gate-check"), ids.index("ai-review-recorded"))

    def test_skipping_a_mandatory_step_requires_reason(self):
        state = new_state("reference.png")
        with self.assertRaises(WorkflowStateError):
            mark_steps(state, ["image-analysis"], status="skipped")
        mark_steps(state, ["image-analysis"], status="skipped", reason="analysis supplied externally")
        entry = next(item for item in state["checklist"] if item["id"] == "image-analysis")
        self.assertEqual(entry["status"], "skipped")

    def test_completing_a_mandatory_step_requires_evidence(self):
        state = new_state("reference.png")
        with self.assertRaises(WorkflowStateError):
            mark_steps(state, ["image-analysis"], status="done")
        mark_steps(state, ["image-analysis"], status="done", evidence=["analysis.json"])
        entry = next(item for item in state["checklist"] if item["id"] == "image-analysis")
        self.assertEqual(entry["evidence"], ["analysis.json"])

    def test_new_pass_archives_and_resets_pass_checklist(self):
        state = new_state("reference.png")
        setup_ids = [entry["id"] for entry in state["checklist"] if entry["scope"] == "setup"]
        mark_steps(state, setup_ids, status="done", evidence=["setup-evidence.json"])
        set_current_pass(state, "blockout")
        mark_steps(
            state,
            ["build-current-pass", "render-capture", "review-contract-read", "tier1-diagnostics"],
            status="done",
            evidence=["shot.png"],
        )
        set_current_pass(state, "structural-pass")
        self.assertEqual(state["passHistory"][0]["passId"], "blockout")
        pass_entries = [entry for entry in state["checklist"] if entry["scope"] == "pass"]
        self.assertTrue(all(entry["status"] == "pending" for entry in pass_entries))

    def test_checklist_cannot_be_completed_out_of_order(self):
        state = new_state("reference.png")
        with self.assertRaisesRegex(WorkflowStateError, "out-of-order"):
            mark_steps(state, ["strict-validation"], status="done", evidence=["spec.json"])

    def test_refine_review_resets_same_pass_checklist_once(self):
        state = new_state("reference.png")
        setup_ids = [entry["id"] for entry in state["checklist"] if entry["scope"] == "setup"]
        pass_ids = [entry["id"] for entry in state["checklist"] if entry["scope"] == "pass"]
        mark_steps(state, setup_ids, status="done", evidence=["setup.json"])
        set_current_pass(state, "blockout")
        mark_steps(state, pass_ids, status="done", evidence=["review.json"])
        self.assertEqual(status_payload(state)["currentStep"], "await-pass-transition")

        spec = {"reviewHistory": [{"passId": "blockout", "action": "refine-code"}]}
        sync_from_spec(state, spec, "blockout")
        self.assertEqual(status_payload(state)["currentStep"], "build-current-pass")
        self.assertIn("do not regenerate", status_payload(state)["nextCommand"])
        self.assertTrue(
            all(entry["status"] == "pending" for entry in state["checklist"] if entry["scope"] == "pass")
        )
        archived = len(state["passHistory"])
        sync_from_spec(state, spec, "blockout")
        self.assertEqual(len(state["passHistory"]), archived)

    def test_new_pass_and_refine_spec_regenerate_with_force(self):
        state = new_state("reference.png", spec="spec.json")
        setup_ids = [entry["id"] for entry in state["checklist"] if entry["scope"] == "setup"]
        mark_steps(state, setup_ids, status="done", evidence=["setup.json"])
        set_current_pass(state, "blockout")
        self.assertNotIn("--force", status_payload(state)["nextCommand"])
        set_current_pass(state, "structural-pass")
        self.assertIn("--force", status_payload(state)["nextCommand"])
        sync_from_spec(
            state,
            {"reviewHistory": [{"passId": "structural-pass", "action": "refine-spec"}]},
            "structural-pass",
        )
        self.assertIn("--force", status_payload(state)["nextCommand"])

    def test_per_pass_refine_limit_is_a_hard_stop(self):
        state = new_state("reference.png", max_per_pass=3, max_total=6)
        spec = {
            "reviewHistory": [
                {"passId": "blockout", "action": "refine-code"},
                {"passId": "blockout", "action": "refine-spec"},
                {"passId": "blockout", "action": "refine-code"},
            ]
        }
        sync_from_spec(state, spec, "blockout")
        payload = status_payload(state)
        self.assertEqual(payload["status"], "stopped")
        self.assertEqual(payload["loop"]["passCount"], 3)
        self.assertIn("max-correction-loops-reached", payload["stopReason"])
        self.assertIsNone(payload["nextCommand"])

    def test_total_refine_limit_is_a_hard_stop(self):
        state = new_state("reference.png", max_per_pass=4, max_total=6)
        spec = {
            "reviewHistory": [
                {"passId": "blockout", "action": "refine-code"},
                {"passId": "blockout", "action": "refine-spec"},
                {"passId": "structural-pass", "action": "refine-code"},
                {"passId": "structural-pass", "action": "refine-spec"},
                {"passId": "form-refinement", "action": "refine-code"},
                {"passId": "form-refinement", "action": "refine-spec"},
            ]
        }
        sync_from_spec(state, spec, "material-pass")
        payload = status_payload(state)
        self.assertEqual(payload["status"], "stopped")
        self.assertIn("max-total-correction-loops-reached", payload["stopReason"])

    def test_next_cli_reads_state_before_a_spec_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            init = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "forge" / "state.py"),
                    "init",
                    "--state",
                    str(state_path),
                    "--reference",
                    "reference.png",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            result = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "next.py"), "--state", str(state_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("LOCAL_STATE status=active step=image-analysis", result.stdout)
            self.assertIn("pending mandatory steps", result.stdout)

    def test_next_cli_reads_state_when_init_recorded_a_spec_path_that_is_not_written_yet(self):
        """`state.py init --spec` records where the spec WILL land.

        SKILL.md's documented opening pair is `state.py init ... --spec object-sculpt-spec.json`
        followed immediately by `next.py --state ...`, so the recorded path is absent for the
        whole pre-spec phase. The mandatory gate must still report the checklist there instead of
        failing, otherwise the pipeline cannot be entered by its own instructions.
        """
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            spec_path = Path(directory) / "object-sculpt-spec.json"
            init = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "forge" / "state.py"),
                    "init",
                    "--state",
                    str(state_path),
                    "--reference",
                    "reference.png",
                    "--spec",
                    str(spec_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            self.assertFalse(spec_path.exists())
            result = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "next.py"), "--state", str(state_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("LOCAL_STATE status=active step=image-analysis", result.stdout)
            self.assertNotIn("spec error", result.stderr)

    def test_next_cli_still_fails_on_an_unreadable_spec_without_state(self):
        """The pre-spec fallback is scoped to --state; a bare missing spec is still an error."""
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "object-sculpt-spec.json"
            result = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "next.py"), str(missing)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("spec error", result.stderr)

    def test_next_cli_reads_a_spec_that_exists_rather_than_the_pre_spec_checklist(self):
        """Negative control for the fallback: once the spec is on disk it must be parsed."""
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            spec_path = Path(directory) / "object-sculpt-spec.json"
            state = new_state("reference.png", spec=str(spec_path))
            setup_ids = [entry["id"] for entry in state["checklist"] if entry["scope"] == "setup"]
            mark_steps(state, setup_ids, status="done", evidence=["setup.json"])
            write_state(state_path, state, action="test-fixture")
            spec_path.write_text(
                json.dumps({"buildPasses": [{"id": "blockout", "acceptance": []}], "reviewHistory": []}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "next.py"), "--state", str(state_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("pass=blockout", result.stdout)

    def test_next_cli_emits_only_state_ordered_build_command(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            spec_path = Path(directory) / "spec.json"
            state = new_state("reference.png", spec=str(spec_path))
            setup_ids = [entry["id"] for entry in state["checklist"] if entry["scope"] == "setup"]
            mark_steps(state, setup_ids, status="done", evidence=["setup.json"])
            write_state(state_path, state, action="test-fixture")
            spec_path.write_text(
                json.dumps({"buildPasses": [{"id": "blockout", "acceptance": []}], "reviewHistory": []}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "next.py"), "--state", str(state_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("generate_threejs_factory.py", result.stdout)
            self.assertNotIn("orchestrate_passes.py check", result.stdout)

    def test_next_cli_rejects_a_spec_that_differs_from_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            stored_spec = Path(directory) / "stored.json"
            other_spec = Path(directory) / "other.json"
            write_state(
                state_path, new_state("reference.png", spec=str(stored_spec)),
                action="test-fixture",
            )
            other_spec.write_text(json.dumps({"buildPasses": []}), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "forge" / "next.py"),
                    str(other_spec),
                    "--state",
                    str(state_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("does not match stored spec", result.stderr)

    def test_journal_detects_unlogged_state_and_log_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            cli = [sys.executable, str(ROOT / "forge" / "state.py")]
            init = subprocess.run(
                [*cli, "init", "--state", str(state_path), "--reference", "reference.png"],
                capture_output=True, text=True,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            mark = subprocess.run(
                [*cli, "mark", "image-analysis", "--state", str(state_path),
                 "--evidence", "observations.json"],
                capture_output=True, text=True,
            )
            self.assertEqual(mark.returncode, 0, mark.stderr)
            journal = state_path.with_name("state.json.transitions.jsonl")
            entries = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(
                [(e["action"], e["step"], e["status"]) for e in entries],
                [("init", "init", "active"), ("mark", "image-analysis", "done")],
            )
            self.assertEqual(entries[1]["previousHash"], entries[0]["entryHash"])
            valid = subprocess.run(
                [*cli, "verify", "--state", str(state_path)], capture_output=True, text=True,
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)
            altered = json.loads(state_path.read_text(encoding="utf-8"))
            altered["checklist"][0]["evidence"] = ["fabricated.png"]
            state_path.write_text(json.dumps(altered), encoding="utf-8")
            for command in (
                [*cli, "verify", "--state", str(state_path)],
                [sys.executable, str(ROOT / "forge" / "next.py"), "--state", str(state_path)],
                [*cli, "mark", "local-spec-search", "--state", str(state_path), "--evidence", "x"],
            ):
                rejected = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(rejected.returncode, 2, rejected.stderr)
                self.assertIn("state tampered", rejected.stderr)
            self.assertEqual(len(journal.read_text(encoding="utf-8").splitlines()), 2)

    def test_legacy_state_migrates_once_and_log_hash_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(json.dumps(new_state("reference.png")), encoding="utf-8")
            cli = [sys.executable, str(ROOT / "forge" / "state.py")]
            old = subprocess.run(
                [*cli, "verify", "--state", str(state_path)], capture_output=True, text=True,
            )
            self.assertEqual(old.returncode, 2)
            self.assertIn("migrate", old.stderr)
            next_old = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "next.py"), "--state", str(state_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(next_old.returncode, 2)
            migrated = subprocess.run(
                [*cli, "migrate", "--state", str(state_path)], capture_output=True, text=True,
            )
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            self.assertIn("previous state history cannot be verified", migrated.stderr)
            verified = subprocess.run(
                [*cli, "verify", "--state", str(state_path)], capture_output=True, text=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            journal = state_path.with_name("state.json.transitions.jsonl")
            entry = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
            entry["status"] = "complete"
            journal.write_text(json.dumps(entry) + "\n", encoding="utf-8")
            broken = subprocess.run(
                [*cli, "verify", "--state", str(state_path)], capture_output=True, text=True,
            )
            self.assertEqual(broken.returncode, 2)
            self.assertIn("tampered transition log", broken.stderr)

    def test_next_sync_writes_valid_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            spec_path = Path(directory) / "spec.json"
            write_state(state_path, new_state("reference.png", spec=str(spec_path)),
                        action="test-fixture")
            spec_path.write_text(
                json.dumps({"buildPasses": [{"id": "blockout", "acceptance": []}], "reviewHistory": []}),
                encoding="utf-8",
            )
            next_run = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "next.py"), "--state", str(state_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(next_run.returncode, 0, next_run.stderr)
            verified = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "state.py"), "verify", "--state", str(state_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            journal = state_path.with_name("state.json.transitions.jsonl")
            entries = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([entry["action"] for entry in entries], ["test-fixture", "sync"])

    def test_state_resume_reopens_pass(self):
        # Upstream #182's public resume --pass-id must work on a ledger-backed state.
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            write_state(state_path, new_state("reference.png"), action="test-fixture")
            cli = [sys.executable, str(ROOT / "forge" / "state.py")]
            resumed = subprocess.run(
                [*cli, "resume", "--state", str(state_path), "--pass-id", "blockout"],
                capture_output=True, text=True,
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            saved = load_state(state_path)
            self.assertEqual(saved["currentPass"], "blockout")
            self.assertEqual(saved["status"], "active")
            self.assertEqual(saved["currentStep"], "image-analysis")
            journal = state_path.with_name("state.json.transitions.jsonl")
            entries = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([entry["sequence"] for entry in entries], [1, 2])
            self.assertEqual([entry["action"] for entry in entries], ["test-fixture", "resume"])
            self.assertEqual(entries[1]["previousHash"], entries[0]["entryHash"])
            checked = subprocess.run(
                [*cli, "verify", "--state", str(state_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            next_run = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "next.py"), "--state", str(state_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(next_run.returncode, 0, next_run.stderr)
            self.assertIn("pass=blockout", next_run.stdout)

    def test_resume_clears_stop_without_bypassing_journal_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state = new_state("reference.png", max_per_pass=1, max_total=1)
            write_state(state_path, state, action="test-fixture")
            sync_from_spec(
                state,
                {"reviewHistory": [{"passId": "blockout", "action": "refine-code"}]},
                "blockout",
            )
            self.assertEqual(state["status"], "stopped")
            write_state(state_path, state, action="sync", steps=("sync",),
                        status=state["status"])
            cli = [sys.executable, str(ROOT / "forge" / "state.py")]
            resumed = subprocess.run(
                [*cli, "resume", "--state", str(state_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            saved = load_state(state_path)
            self.assertEqual(saved["currentPass"], "blockout")
            self.assertEqual(saved["status"], "active")
            self.assertEqual(saved["stopReason"], "")
            self.assertEqual(saved["currentStep"], "image-analysis")
            journal = state_path.with_name("state.json.transitions.jsonl")
            entries = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([entry["sequence"] for entry in entries], [1, 2, 3])
            self.assertEqual([entry["action"] for entry in entries], ["test-fixture", "sync", "resume"])
            self.assertEqual(entries[2]["previousHash"], entries[1]["entryHash"])
            verified = subprocess.run(
                [*cli, "verify", "--state", str(state_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)

            # Direct edits must not be able to exploit resume to legitimize them.
            saved["currentPass"] = "forged"
            state_path.write_text(json.dumps(saved), encoding="utf-8")
            rejected = subprocess.run(
                [*cli, "resume", "--state", str(state_path), "--pass-id", "structural-pass"],
                capture_output=True, text=True,
            )
            self.assertEqual(rejected.returncode, 2, rejected.stderr)
            self.assertIn("state tampered", rejected.stderr)
            self.assertEqual(len(journal.read_text(encoding="utf-8").splitlines()), 3)

    def test_state_cli_does_not_expose_manual_pass_bypass(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "forge" / "state.py"), "set-pass", "complete"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)

    def test_next_cli_returns_nonzero_at_loop_ceiling(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            spec_path = Path(directory) / "spec.json"
            state = new_state("reference.png", spec=str(spec_path), max_per_pass=2, max_total=6)
            write_state(state_path, state, action="test-fixture")
            spec_path.write_text(
                json.dumps(
                    {
                        "buildPasses": [{"id": "blockout", "acceptance": []}],
                        "reviewHistory": [
                            {"passId": "blockout", "action": "refine-code"},
                            {"passId": "blockout", "action": "refine-spec"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "forge" / "next.py"), "--state", str(state_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertIn("STOP: max-correction-loops-reached", result.stdout)

    def test_skill_router_keeps_mandatory_state_and_reference_gates_visible(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("forge/next.py --state .img2threejs/state.json", skill)
        # The rule that matters is that the contract-read is mandatory and complete, not which
        # domain owns the contract -- the router names no domain.
        self.assertIn("MUST read the contract its step names, completely", skill)
        self.assertIn("MUST read\n   `grimoire/review/gates_reference.md`", skill)
        self.assertIn("forge/stage4_review/diagnose_render.py", skill)
        self.assertIn("forge/stage4_review/diagnose_render_multi_angle.py", skill)
        self.assertIn("forge/stage4_review/check_part_coverage.py", skill)

    def test_all_direct_router_references_exist(self):
        for relative in (
            # cs2_intake_contract.md is deliberately absent: it ships with the CS2 domain plugin,
            # so a base checkout must NOT be expected to hold it.
            "grimoire/intake/local_spec_search.md",
            "grimoire/review/gates_reference.md",
            "grimoire/review/self_correction.md",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
