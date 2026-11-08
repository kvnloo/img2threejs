"""Detect unlogged edits to the local checklist state.

The chained log is tamper-evident, not secure against an agent able to rewrite
both files and recompute the hashes. Stronger attestation needs an external anchor.
"""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from workflow_state import WorkflowStateError, load_state, recompute, save_state, validate_state

ZERO_HASH = "0" * 64


def journal_path(path: Path) -> Path:
    target = path.expanduser().resolve()
    return target.with_name(target.name + ".transitions.jsonl")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_journal(path: Path) -> list[dict[str, Any]]:
    journal = journal_path(path)
    if not journal.exists():
        raise WorkflowStateError(
            "legacy state has no transition log; run "
            f"'python3 forge/state.py migrate --state {path}' once; "
            "history before migration cannot be verified"
        )
    entries: list[dict[str, Any]] = []
    previous = ZERO_HASH
    try:
        with journal.open("r", encoding="utf-8") as stream:
            for sequence, line in enumerate(stream, 1):
                try:
                    entry = json.loads(line)
                except ValueError as error:
                    raise WorkflowStateError(f"invalid transition log entry {sequence}") from error
                if not isinstance(entry, dict):
                    raise WorkflowStateError(f"invalid transition log entry {sequence}")
                if entry.get("sequence") != sequence or entry.get("previousHash") != previous:
                    raise WorkflowStateError(f"broken transition log chain at entry {sequence}")
                if not all(isinstance(entry.get(key), str) for key in
                           ("timestamp", "action", "step", "status", "stateSha256")):
                    raise WorkflowStateError(f"invalid transition metadata at entry {sequence}")
                if not isinstance(entry.get("evidence"), list) or not all(
                    isinstance(item, str) for item in entry["evidence"]
                ):
                    raise WorkflowStateError(f"invalid transition evidence at entry {sequence}")
                checksum = _digest({k: v for k, v in entry.items() if k != "entryHash"})
                if entry.get("entryHash") != checksum:
                    raise WorkflowStateError(f"tampered transition log entry {sequence}")
                entries.append(entry)
                previous = checksum
    except OSError as error:
        raise WorkflowStateError(f"cannot read transition log: {error}") from error
    if not entries:
        raise WorkflowStateError("transition log is empty")
    return entries


def _assert_derived(state: dict[str, Any]) -> None:
    derived = deepcopy(state)
    recompute(derived)
    if (state.get("status"), state.get("currentStep")) != (
        derived.get("status"), derived.get("currentStep")
    ):
        raise WorkflowStateError("derived status/currentStep disagrees with checklist")


def verify_state(path: Path, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    current = load_state(path) if state is None else validate_state(state)
    _assert_derived(current)
    entries = _read_journal(path)
    if entries[-1]["stateSha256"] != _digest(current):
        raise WorkflowStateError("state tampered: state.json differs from last transition")
    return entries


def _append(path: Path, state: dict[str, Any], history: list[dict[str, Any]],
            *, action: str, steps: Iterable[str], status: str, evidence: Iterable[str]) -> None:
    previous = history[-1]["entryHash"] if history else ZERO_HASH
    sequence = len(history)
    digest = _digest(state)
    with journal_path(path).open("a", encoding="utf-8") as stream:
        for step in steps:
            sequence += 1
            entry = {
                "sequence": sequence,
                "previousHash": previous,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "step": step,
                "status": status,
                "evidence": list(evidence),
                "stateSha256": digest,
            }
            entry["entryHash"] = _digest(entry)
            stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            previous = entry["entryHash"]
        stream.flush()
        os.fsync(stream.fileno())


def write_state(path: Path, state: dict[str, Any], *, action: str,
                steps: Iterable[str] = ("",), status: str = "",
                evidence: Iterable[str] = ()) -> None:
    validate_state(state)
    _assert_derived(state)
    target = path.expanduser().resolve()
    if target.exists():
        history = verify_state(target)
    else:
        if journal_path(target).exists():
            raise WorkflowStateError("orphaned transition log; refusing to replace state")
        history = []
    steps = tuple(steps)
    if not steps:
        raise WorkflowStateError("state transition requires a step")
    save_state(target, state)
    try:
        _append(target, state, history, action=action, steps=steps, status=status, evidence=evidence)
    except OSError as error:
        raise WorkflowStateError(f"cannot append transition log: {error}") from error


def migrate_state(path: Path, state: dict[str, Any]) -> None:
    target = path.expanduser().resolve()
    if journal_path(target).exists():
        raise WorkflowStateError("transition log already exists; use state.py verify")
    if not target.is_file():
        raise WorkflowStateError(f"state file does not exist: {target}")
    validate_state(state)
    recompute(state)
    save_state(target, state)
    try:
        _append(target, state, [], action="migrate", steps=("migrate",),
                status=state["status"], evidence=())
    except OSError as error:
        raise WorkflowStateError(f"cannot initialize transition log: {error}") from error
