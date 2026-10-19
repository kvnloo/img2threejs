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
        # The recorder persists these fields when the browser capture is taken.
        # Matching file bytes alone cannot establish that a receipt still
        # describes those bytes if the receipt was copied from another run.
        # Require the saved dimensions and encoding to agree with the file.
        recorded_image = record.get("image")
        if not isinstance(recorded_image, dict) or any(
            recorded_image.get(field) != image.get(field)
            for field in ("type", "width", "height")
        ):
            return "image-receipt-mismatch"
    except (OSError, ValueError, TypeError):
        return "unreadable-screenshot"
    return None


def resume_plan(manifest_file: Path) -> dict[str, Any]:
    manifest_file = manifest_file.expanduser().resolve()
    manifest = read_manifest(manifest_file)
    reference = manifest.get("reference")
    if not isinstance(reference, dict) or reference.get("kind") not in ("image", "glb"):
        raise ValueError("reference.kind must be image or glb")
    # A changed source image/GLB invalidates every camera comparison, even if
    # each old screenshot still matches its own saved digest.
    source = reference.get("path")
    expected = reference.get("sha256")
    if not isinstance(source, str) or not source.strip() or not isinstance(expected, str):
        raise ValueError("source reference path and SHA-256 are required")
    source_path = manifest_path(manifest_file, source)
    if not source_path.is_file() or sha256(source_path) != expected.lower():
        raise ValueError("source reference hash changed or file is missing")
    # A v2 render profile defines the camera/lighting environment shared by GLB
    # reference and procedural shots. A profile edit makes otherwise intact
    # screenshot receipts incomparable; do not reuse them across that boundary.
    if manifest.get("fidelityTrack") == "glb-mediated-v2":
        profile = manifest.get("renderProfile")
        if not isinstance(profile, dict):
            raise ValueError("GLB-mediated resume requires renderProfile")
        profile_name, profile_hash = profile.get("path"), profile.get("sha256")
        if not isinstance(profile_name, str) or not profile_name.strip():
            raise ValueError("GLB-mediated resume requires renderProfile.path")
        if (
            not isinstance(profile_hash, str)
            or len(profile_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in profile_hash)
        ):
            raise ValueError("GLB-mediated resume requires a lowercase renderProfile.sha256")
        profile_path = manifest_path(manifest_file, profile_name)
        if not profile_path.is_file() or sha256(profile_path) != profile_hash:
            raise ValueError("render profile hash changed or file is missing")
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
