#!/usr/bin/env python3
"""Optional real-browser mesh -> STL/OBJ bridge verification.

Uses an independent trimesh importer, installed only in opt-in integration CI.
The core print exporter stays dependency-free.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRINT_CLI = ROOT / "forge" / "stage3_build" / "print_export.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(source: Path, output: Path, report: Path, *, extra: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable, str(PRINT_CLI), str(source), "--out", str(output),
            "--longest-edge-mm", "100", "--report", str(report), "--json", *extra,
        ],
        capture_output=True, text=True, check=False, cwd=ROOT,
    )


def need(ok: object, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def comparable(a: float, b: float, tolerance: float = 0.025) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance


def verify_files(source: Path, output_dir: Path, prefix: str) -> dict:
    import trimesh  # CI-only independent parser; not a core runtime dependency.

    need(source.is_file(), f"browser exporter source missing: {source}")
    receipt = json.loads(source.read_text(encoding="utf-8"))
    need(isinstance(receipt, dict), "browser evidence must be a JSON object")
    need(receipt.get("incomplete") is False, "browser evidence is incomplete")
    need(receipt.get("coordinateSpace") == "world", "browser evidence is not world-space")
    need(receipt.get("sceneRootOptIn") is False, "scene/studio-root export is not valid print evidence")
    source_count = len(receipt.get("meshes", []))
    need(source_count >= 2, f"expected at least two captured meshes: {prefix}")

    formats: dict[str, dict] = {}
    for kind in ("stl", "obj"):
        output = output_dir / f"{prefix}.{kind}"
        report_path = output_dir / f"{prefix}.{kind}.report.json"
        result = invoke(source, output, report_path)
        need(result.returncode == 0, f"{prefix}.{kind}: exporter refused browser mesh: {result.stderr} {result.stdout}")
        need(output.is_file() and report_path.is_file(), "print file/report missing")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        need(report["printable"] is True and report["written"] is True and report["watertight"] is True,
             f"{prefix}.{kind} not certified watertight: {report}")
        need(report["sourceMeshCount"] == source_count, "source mesh count changed")
        need(report["insideOutShellCount"] == 0 and report["zeroVolumeShellCount"] == 0, "bad closed shell")
        need(report["nonManifoldEdgeCount"] == 0 and report["nonManifoldVertexCount"] == 0, "nonmanifold shell")
        need(report["shellCount"] >= 2, "expected multiple independent closed shells")
        need(report["units"] == "mm", "print dimensions must be millimeters")
        need(comparable(max(report["bounds"]["size"]), 100, 0.0001), "longest-edge scaling is wrong")

        # The independent library consumes the produced bytes, not our in-memory geometry.
        external = trimesh.load_mesh(str(output), force="mesh", process=True)
        need(isinstance(external, trimesh.Trimesh), "independent importer did not return Trimesh")
        need(len(external.faces) > 0 and bool(external.is_watertight),
             f"independent {kind} importer found open/empty geometry")
        need(bool(external.is_winding_consistent), f"independent {kind} importer found reversed faces")
        need(external.volume > 0 and math.isfinite(float(external.volume)),
             f"independent {kind} importer found no positive solid volume")
        need(all(comparable(float(observed), float(expected))
                 for observed, expected in zip(external.extents, report["bounds"]["size"])),
             f"independent {kind} bounds disagree with print report")
        need(comparable(float(external.volume), float(report["volume"]),
                        max(0.025, 0.002 * float(report["volume"]))),
             f"independent {kind} volume disagrees with report")
        formats[kind] = {
            "file": output.name, "sha256": sha256(output), "bytes": output.stat().st_size,
            "importedVolumeMm3": float(external.volume),
            "importedExtentsMm": [float(value) for value in external.extents],
            "importedWatertight": bool(external.is_watertight),
            "importedWindingConsistent": bool(external.is_winding_consistent),
            "shellCount": int(report["shellCount"]), "triangleCount": int(report["triangleCount"]),
        }

    need(all(comparable(formats["stl"]["importedExtentsMm"][i],
                        formats["obj"]["importedExtentsMm"][i]) for i in range(3)),
         "STL and OBJ dimension disagreement")
    need(comparable(formats["stl"]["importedVolumeMm3"],
                    formats["obj"]["importedVolumeMm3"],
                    max(0.025, 0.002 * formats["obj"]["importedVolumeMm3"])),
         "STL and OBJ volume disagreement")
    if prefix == "instances":
        need(source_count == 2, "two browser instances should expand into two independent meshes")
        need(comparable(formats["stl"]["importedVolumeMm3"], 16000, 0.025),
             "two separated 20-mm boxes should have 16,000 mm3 total volume")
        need(all(comparable(a, b) for a, b in zip(
            formats["stl"]["importedExtentsMm"], (100, 20, 20)
        )), "world-space instance translation or scaling was lost")
    return {"sourceReceipt": source.name, "sourceSha256": sha256(source),
            "sourceMeshCount": source_count, "formats": formats}


def verify_refusals(incomplete_path: Path, good_source: Path, output_dir: Path) -> dict:
    need(incomplete_path.is_file(), "actual partial browser capture receipt missing")
    incomplete = json.loads(incomplete_path.read_text(encoding="utf-8"))
    need(incomplete.get("incomplete") is True, "browser partial capture was not flagged incomplete")
    staged = output_dir / "stale-output.stl"
    old = b"untouched-prior-export"
    staged.write_bytes(old)
    report_path = output_dir / "rejected-partial.report.json"
    result = invoke(incomplete_path, staged, report_path, extra=("--allow-open", "--force"))
    need(result.returncode == 2, f"partial browser receipt unexpectedly accepted: {result.stdout}")
    need(staged.read_bytes() == old and not report_path.exists(),
         "partial input overwrote a known-good export or published a report")

    forged = json.loads(good_source.read_text(encoding="utf-8"))
    forged["coordinateSpace"] = "local"
    wrong_space = output_dir / "wrong-space.json"
    wrong_space.write_text(json.dumps(forged), encoding="utf-8")
    local_report = output_dir / "rejected-local.report.json"
    result = invoke(wrong_space, staged, local_report, extra=("--allow-open", "--force"))
    need(result.returncode == 2, f"local-space geometry unexpectedly accepted: {result.stdout}")
    need(staged.read_bytes() == old and not local_report.exists(),
         "wrong-coordinate input clobbered prior STL")

    # An apparently complete receipt must not hide active missing parts.
    # This protects against a buggy producer that sets incomplete:false
    # but still reports skipped skinned geometry or budget overrun.
    lied = json.loads(good_source.read_text(encoding="utf-8"))
    lied["incomplete"] = False
    lied["skippedMeshes"] = [{"name": "skinned-arm", "reason": "skinned-mesh"}]
    lied_path = output_dir / "false-complete.json"
    lied_path.write_text(json.dumps(lied), encoding="utf-8")
    skipped_report = output_dir / "rejected-skipped.report.json"
    result = invoke(lied_path, staged, skipped_report, extra=("--allow-open", "--force"))
    need(result.returncode == 2, f"active skipped geometry was printed: {result.stdout}")
    need(staged.read_bytes() == old and not skipped_report.exists(),
         "false-complete evidence overwrote prior STL or published a report")
    return {"realPartialBrowserReceiptRejected": True,
            "fabricatedLocalCoordinateReceiptRejected": True,
            "falseCompleteWithActiveSkippedMeshRejected": True,
            "existingSTLPreservedDespiteForceAndAllowOpen": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-artifacts", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    src_dir = args.browser_artifacts.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        payload = {
            "kind": "actual-threejs-browser-to-independent-print-import",
            "exporterDependency": "pinned downstream PR #35",
            "referenceFidelity": "not evaluated",
            "slicerValidation": "not evaluated",
            "verified": {
                "instances": verify_files(src_dir / "instances.json", out_dir, "instances"),
                "generated": verify_files(src_dir / "generated-factory-meshes.json", out_dir, "generated"),
            },
            "negative": verify_refusals(
                src_dir / "meshes.json.incomplete.json",
                src_dir / "instances.json", out_dir,
            ),
        }
        (out_dir / "integration-report.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print("PASS: real Chromium/Three.js -> world-space meshes -> STL/OBJ -> trimesh")
        print(json.dumps(payload, indent=2))
        return 0
    except (OSError, ValueError, AssertionError, KeyError, TypeError) as exc:
        print(f"PRINT E2E FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
