#!/usr/bin/env python3
"""Read-only resume queue for a partially recorded Three.js capture manifest."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from render_bridge import manifest_path, probe, read_manifest, sha256


def receipt_error(manifest_file: Path, record: Any) -> str | None:
    if not isinstance(record, dict) or record.get("status") != "recorded":
        return "not-recorded"
    ready = record.get("readySignal")
    if ready is not True and not (isinstance(ready, str) and ready.strip().lower() == "true"):
        return "not-ready"
    if record.get("consoleErrors") != []:
        return "console-errors-or-unverified"
    path = record.get("path")
    if not isinstance(path, str) or not path.strip():
        return "no-screenshot-path"
    screenshot = manifest_path(manifest_file, path)
    digest = record.get("screenshotSha256")
    if not isinstance(digest, str) or len(digest) != 64:
        return "missing-sha256"
    if not all(ch in "0123456789abcdefABCDEF" for ch in digest):
        return "invalid-sha256"
    try:
        if not screenshot.is_file():
            return "missing-screenshot"
        if sha256(screenshot) != digest.lower():
            return "changed-screenshot"
        image = probe(screenshot)
        if not image.get("type") or not image.get("width") or not image.get("height"):
            return "unreadable-screenshot"
    except (OSError, ValueError, TypeError):
        return "unreadable-screenshot"
    return None


def resume_plan(manifest_file: Path) -> dict[str, Any]:
    manifest_file = manifest_file.expanduser().resolve()
    manifest = read_manifest(manifest_file)
    reference = manifest.get("reference")
    if not isinstance(reference, dict) or reference.get("kind") not in ("image", "glb"):
        raise ValueError("reference.kind must be image or glb")
    captures = manifest.get("captures")
    if not isinstance(captures, list) or not captures:
        raise ValueError("captures must be a nonempty list")
    pending = []
    seen = set()
    verified = 0
    for view in captures:
        if not isinstance(view, dict) or not isinstance(view.get("id"), str) or not view["id"]:
            raise ValueError("capture must have a nonempty id")
        if view["id"] in seen:
            raise ValueError("duplicate capture id: " + view["id"])
        seen.add(view["id"])
        modes = ("reference", "procedural") if reference["kind"] == "glb" else ("procedural",)
        for mode in modes:
            record = view.get("reference") if mode == "reference" else view
            reason = receipt_error(manifest_file, record)
            if reason is None:
                verified += 1
            else:
                pending.append({
                    "captureId": view["id"], "mode": mode,
                    "azimuthDegrees": view.get("azimuthDegrees"),
                    "elevationDegrees": view.get("elevationDegrees"),
                    "reason": reason,
                })
    return {
        "verifiedShots": verified, "requiredShots": verified + len(pending),
        "captureShotsComplete": not pending,
        "next": pending[0] if pending else None, "remaining": pending,
        "fullReviewPassed": False,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = resume_plan(args.manifest)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"resume error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
