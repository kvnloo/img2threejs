#!/usr/bin/env python3
"""Compact, fail-closed browser-evidence status for agent context windows.

This is a summary of the existing render manifest, NOT a substitute for
screenshots, pixel comparison, Tier-1 diagnostics, or human/agent visual review.
Raw DOM, URLs, console text, browser logs and absolute paths never enter output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from render_bridge import CAPTURE_PLAN, read_manifest, validate_manifest

SCHEMA = "img2threejs-browser-brief-v1"
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
# Only repository-owned camera identifiers are allowed in an agent summary.
# Other IDs are untrusted free text, even if they look like safe ASCII slugs.
_PUBLIC_CAPTURE_IDS = frozenset(row["id"] for row in CAPTURE_PLAN)


def _has_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _short_id(value: Any, index: int) -> str:
    """Expose canonical public camera labels, never untrusted capture names.

    A secret can contain only letters, numbers, underscores and dots; an
    ASCII/length sanitizer cannot distinguish it from an innocuous slug.
    Fallback labels use list positions, not truncated input substrings.
    """
    return value if isinstance(value, str) and value in _PUBLIC_CAPTURE_IDS else f"capture-{index}"


def _has_browser_errors(value: Any) -> bool:
    # A malformed nonempty string is not a clean error receipt either.
    return bool(value) or (value is not None and not isinstance(value, list))


def build_brief(path: Path, *, since: str = "", max_ids: int = 8) -> dict[str, Any]:
    """Revalidate evidence on every call, including when the manifest digest matches.

    Digest-only caching without revalidation could hide a modified PNG under
    an unchanged manifest, so only healthy evidence may produce an unchanged reply.
    """
    if not 1 <= max_ids <= 20:
        raise ValueError("max_ids must be from 1 to 20")
    path = path.expanduser().resolve()
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    manifest = read_manifest(path)
    validation = validate_manifest(path, require_complete=True)
    captures = manifest.get("captures")
    if not isinstance(captures, list):
        captures = []
    reference = manifest.get("reference")
    reference = reference if isinstance(reference, dict) else {}
    evidence = manifest.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    v2 = manifest.get("fidelityTrack") == "glb-mediated-v2"

    categories: set[str] = set()
    pending: list[str] = []
    repair: list[str] = []
    observed: set[str] = set()
    recorded = 0
    for index, capture in enumerate(captures):
        if not isinstance(capture, dict):
            categories.add("invalid-capture")
            repair.append(f"capture-{index}")
            continue
        raw_id = capture.get("id")
        cid = _short_id(raw_id, index)
        if not isinstance(raw_id, str) or not raw_id:
            categories.add("invalid-capture")
            repair.append(cid)
        else:
            # Identity is the original ID, never a truncated/redacted display alias.
            if raw_id in observed:
                categories.add("duplicate-capture")
                repair.append(cid)
            observed.add(raw_id)
        if capture.get("status") != "recorded":
            pending.append(cid)
            continue
        recorded += 1
        if capture.get("readySignal") is not True:
            categories.add("missing-readiness")
            repair.append(cid)
        if not capture.get("path") or not _has_sha(capture.get("screenshotSha256")):
            categories.add("missing-capture-hash")
            repair.append(cid)
        if _has_browser_errors(capture.get("consoleErrors")):
            categories.add("browser-error")
            repair.append(cid)
        if reference.get("kind") == "glb":
            baseline = capture.get("reference")
            if not isinstance(baseline, dict) or baseline.get("status") != "recorded":
                categories.add("missing-glb-baseline")
                repair.append(cid)
            else:
                if baseline.get("readySignal") is not True:
                    categories.add("missing-readiness")
                    repair.append(cid)
                if not baseline.get("path") or not _has_sha(baseline.get("screenshotSha256")):
                    categories.add("missing-capture-hash")
                    repair.append(cid)
                if _has_browser_errors(baseline.get("consoleErrors")):
                    categories.add("browser-error")
                    repair.append(cid)
        if v2:
            for record in (capture, capture.get("reference") if reference.get("kind") == "glb" else None):
                if record is None:
                    continue
                passes = record.get("passes") if isinstance(record, dict) else None
                if not isinstance(passes, dict) or any(
                    not isinstance(value, dict) or value.get("status") != "recorded"
                    for value in passes.values()
                ) or not passes:
                    categories.add("missing-diagnostic-passes")
                    repair.append(cid)

    if manifest.get("schemaVersion") != 1:
        categories.add("invalid-schema")
    if reference.get("kind") not in {"image", "glb"} or not _has_sha(reference.get("sha256")):
        categories.add("unverified-reference")
    if _has_browser_errors(evidence.get("consoleErrors")):
        categories.add("browser-error")
    errors = validation.get("errors", [])
    if not isinstance(errors, list):
        categories.add("invalid-validation")
        errors = ["invalid validation response"]
    if errors or validation.get("passed") is not True:
        categories.add("failed-manifest-validation")

    complete = (
        bool(captures) and not categories and not pending and recorded == len(captures)
    )
    if complete and since == digest:
        return {
            "schema": SCHEMA,
            "digest": digest,
            "unchanged": True,
            "evidenceComplete": True,
            "visualAcceptance": "not-assessed",
        }
    # Invalid reference provenance, stale hashes, unready screenshots or
    # browser errors must be repaired before collecting additional views.
    # Otherwise the next camera action can run against unusable evidence.
    next_step = "repair-evidence" if categories else "capture-missing" if pending else "visual-review"
    return {
        "schema": SCHEMA,
        "digest": digest,
        "manifestBytes": len(raw),
        "evidenceComplete": complete,
        "visualAcceptance": "not-assessed",
        "referenceKind": reference.get("kind") if reference.get("kind") in {"image", "glb"} else "invalid",
        "capturesPlanned": len(captures),
        "capturesRecorded": recorded,
        "pendingCount": len(pending),
        "pendingIds": pending[:max_ids],
        "repairCount": len(set(repair)),
        "repairIds": list(dict.fromkeys(repair))[:max_ids],
        "validationErrorCount": len(errors),
        "errorCategories": sorted(categories),
        "nextStep": next_step,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--since", default="", help="prior digest for an unchanged-success receipt")
    parser.add_argument("--max-ids", type=int, default=8)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit 1 when evidence is incomplete")
    args = parser.parse_args(argv)
    try:
        result = build_brief(args.manifest, since=args.since, max_ids=args.max_ids)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        # An invalid nested reference object can trigger AttributeError in an
        # older render_bridge validator. Fail closed without printing its
        # absolute-path traceback or any raw manifest data.
        print(f"browser brief: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":") if not args.pretty else None,
                     indent=2 if args.pretty else None))
    return 1 if args.strict and not result["evidenceComplete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
