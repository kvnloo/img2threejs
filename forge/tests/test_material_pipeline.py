#!/usr/bin/env python3
"""End-to-end contracts for the nine-phase material pipeline."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stage1_intake"))
sys.path.insert(0, str(ROOT / "stage2_spec"))
sys.path.insert(0, str(ROOT / "stage4_review"))

from materials.compatibility import check_compatibility  # noqa: E402
from materials.reference import build_assignment, load_reference, resolve_material  # noqa: E402
from material_region_analysis import _contained_artifact, _safe_region_token, analyze_manifest  # noqa: E402
from extract_pbr_evidence import slugify  # noqa: E402
from apply_material_analysis import apply_material_analysis  # noqa: E402
from material_comparator import compare_material_crops  # noqa: E402
from material_feedback import apply_material_feedback  # noqa: E402
from material_gate import run_material_gate  # noqa: E402
from material_views import build_view_plan, crop_visible_footprint, validate_capture  # noqa: E402


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_png(path: Path, width: int, height: int, fn) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return len(data).to_bytes(4, "big") + kind + data + (zlib.crc32(kind + data) & 0xFFFFFFFF).to_bytes(4, "big")
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(bytes(fn(x, y)))
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((8, 2, 0, 0, 0))
    path.write_bytes(PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b""))


class MaterialPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="img2threejs-material-pipeline-"))
        self.registry = load_reference()
        self.reference = self.tmp / "armor.png"
        write_png(
            self.reference,
            512,
            512,
            lambda x, y: (246, 246, 246) if x < 64 or x >= 448 or y < 64 or y >= 448 else (
                24 + (x * 5 + y * 3) % 190,
                42 + (x * 7 + y * 11) % 150,
                80 + (x * 13 + y * 17) % 150,
            ),
        )

    def test_phase_one_resolver_preserves_authority_and_ambiguity(self) -> None:
        exact = resolve_material({"materialId": "coating.painted-metal", "confidence": 0.2}, self.registry)
        self.assertEqual(exact["status"], "proceed")
        self.assertEqual(exact["method"], "explicit-material-id")
        assignment = build_assignment({"family": "coating", "subtype": "paint-over-metal", "finish": "gloss-or-satin", "confidence": 0.9}, {}, self.registry)
        self.assertEqual(assignment["profileId"], "coating.painted-metal")
        self.assertIn("roughness", assignment["renderPrior"])
        ambiguous = resolve_material({"family": "metal", "confidence": 0.4}, self.registry)
        self.assertIn(ambiguous["status"], {"request-input", "probe"})

    def test_phases_two_to_nine_vertical_slice(self) -> None:
        manifest = self.tmp / "regions.json"
        manifest.write_text(json.dumps({
            "referenceId": "armor-fixture",
            "regions": [{
                "componentId": "torso-armor",
                "regionId": "paint",
                "sourceImage": str(self.reference),
                "bbox": {"x": 64, "y": 64, "width": 384, "height": 384},
                "family": "coating",
                "subtype": "paint-over-metal",
                "finish": "gloss-or-satin",
                "materialSpecId": "armor-paint",
            }],
        }, indent=2), encoding="utf-8")
        analysis = analyze_manifest(manifest, self.tmp / "analysis-data")
        self.assertEqual(analysis["status"], "proceed")
        region = analysis["regions"][0]
        self.assertEqual(region["assignment"]["profileId"], "coating.painted-metal")
        self.assertTrue(Path(region["crop"]["path"]).exists())
        self.assertTrue(region["referencePbr"]["maps"]["roughness"]["path"])

        spec = {
            "materials": [{"id": "armor-paint", "baseColor": "#20344A", "textureProjection": {"mode": "uv", "repeat": [1, 1]}}],
            "componentTree": [{"id": "torso-armor", "material": "armor-paint", "uvContract": {"status": "unwrapped"}}],
            "lodPlan": [{"id": "lod0", "materialIds": ["armor-paint"]}],
            "rig": {"bones": [{"id": "torso", "component": "torso-armor"}]},
            "collisionGroups": {"torso-armor": "box"},
        }
        spec = apply_material_analysis(spec, analysis)
        self.assertEqual(spec["materialPipeline"]["status"], "proceed")
        self.assertEqual(spec["materials"][0]["referenceMaterialId"], "coating.painted-metal")
        compatibility = check_compatibility(spec)
        self.assertTrue(compatibility["passed"], compatibility)

        crop = Path(region["crop"]["path"])
        render = self.tmp / "render.png"
        render.write_bytes(crop.read_bytes())
        comparison = compare_material_crops(crop, render, material_id="armor-paint", expected=region["assignment"])
        self.assertTrue(comparison["passed"], comparison)
        plan = build_view_plan("torso-armor", "paint", validation_views=["neutral-studio", "grazing", "environment-reflection"])
        self.assertGreaterEqual(len(plan["views"]), 12)
        crop_meta = crop_visible_footprint(crop, {"x": 0, "y": 0, "width": 384, "height": 384}, self.tmp / "microscope.png")
        self.assertTrue(validate_capture(Path(crop_meta["path"]))["passed"])

        feedback = apply_material_feedback(spec, "armor-paint", comparison)
        self.assertEqual(feedback["decision"]["action"], "continue")
        gate = run_material_gate(spec, analysis=analysis, comparisons=[comparison], view_plan=plan)
        self.assertTrue(gate["passed"], gate)

    def test_region_id_cannot_escape_material_output_directory(self) -> None:
        manifest = self.tmp / "regions-path-traversal.json"
        manifest.write_text(json.dumps({
            "referenceId": "path-safety-fixture",
            "regions": [{
                "componentId": "torso-armor",
                "regionId": "..\\..//escape",
                "sourceImage": str(self.reference),
                "bbox": {"x": 64, "y": 64, "width": 384, "height": 384},
                "family": "coating",
                "subtype": "paint-over-metal",
                "finish": "gloss-or-satin",
                "materialSpecId": "armor-paint",
            }],
        }), encoding="utf-8")
        out_dir = self.tmp / "contained-analysis"
        analysis = analyze_manifest(manifest, out_dir)
        crop = Path(analysis["regions"][0]["crop"]["path"]).resolve()
        self.assertTrue(crop.is_relative_to(out_dir.resolve()))
        self.assertNotIn("..", crop.name)
        self.assertNotIn("\\", crop.name)
        self.assertFalse((self.tmp / "escape.png").exists())

    def test_region_tokens_are_bounded_and_distinguish_long_ids(self) -> None:
        normal = "paint-main_02"
        self.assertEqual(_safe_region_token(normal), normal)
        self.assertEqual(_safe_region_token("../..\\\\paint"), "paint")
        left = "body-" + "x" * 500 + "-left"
        right = "body-" + "x" * 500 + "-right"
        self.assertNotEqual(_safe_region_token(left), _safe_region_token(right))
        self.assertLessEqual(len(_safe_region_token(left)), 93)
        self.assertEqual(_safe_region_token(left), _safe_region_token(left))

    def test_long_region_id_does_not_make_oversized_pbr_map_files(self) -> None:
        region_id = "coating-" + "x" * 500
        manifest = self.tmp / "regions-long-id.json"
        manifest.write_text(json.dumps({
            "referenceId": "long-region-id-fixture",
            "regions": [{
                "componentId": "torso-armor",
                "regionId": region_id,
                "sourceImage": str(self.reference),
                "bbox": {"x": 64, "y": 64, "width": 384, "height": 384},
                "family": "coating",
                "subtype": "paint-over-metal",
                "finish": "gloss-or-satin",
            }],
        }), encoding="utf-8")
        out_dir = self.tmp / "long-id-analysis"
        result = analyze_manifest(manifest, out_dir)
        region = result["regions"][0]
        self.assertEqual(region["regionId"], region_id)
        self.assertEqual(region["materialSpecId"], region_id)
        self.assertLessEqual(len(slugify(region_id).encode("utf-8")), 80)
        self.assertNotEqual(slugify(region_id), slugify(region_id + "-different"))
        for entry in region["referencePbr"]["maps"].values():
            path = Path(entry["path"])
            self.assertTrue(path.is_file(), path)
            self.assertTrue(path.resolve().is_relative_to(out_dir.resolve()))
            self.assertLessEqual(len(path.name.encode("utf-8")), 255)

    def test_pbr_slug_is_bounded_by_utf8_bytes_not_codepoints(self) -> None:
        long_multibyte = "界" * 100
        self.assertLessEqual(len(slugify(long_multibyte).encode("utf-8")), 80)
        self.assertEqual(slugify("paint-main_02"), "paint-main-02")

    def test_symlinked_crop_and_pbr_artifacts_are_refused(self) -> None:
        out_dir = self.tmp / "out-with-links"
        out_dir.mkdir()
        outside_file = self.tmp / "outside.png"
        outside_file.write_bytes(b"untouched")
        outside_dir = self.tmp / "outside-pbr"
        outside_dir.mkdir()
        for name, target, directory in (
            ("00-paint.png", outside_file, False),
            ("pbr-00-paint", outside_dir, True),
        ):
            link = out_dir / name
            try:
                link.symlink_to(target, target_is_directory=directory)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            try:
                with self.assertRaisesRegex(ValueError, "artifact path escapes output directory"):
                    _contained_artifact(out_dir, name)
            finally:
                link.unlink()
        self.assertEqual(outside_file.read_bytes(), b"untouched")

    def test_low_confidence_analysis_cannot_enter_without_override(self) -> None:
        analysis = {
            "status": "probe",
            "registry": str(ROOT / ".." / "docs/materials/material-reference.json"),
            "regions": [{"regionId": "paint", "status": "probe"}],
        }
        spec = {"materials": [], "componentTree": []}
        with self.assertRaises(ValueError):
            apply_material_analysis(spec, analysis)

    def test_unobserved_material_keeps_pipeline_probe_even_when_visible_regions_pass(self) -> None:
        manifest = self.tmp / "regions-with-unobserved.json"
        manifest.write_text(json.dumps({
            "referenceId": "armor-fixture-with-hidden-material",
            "notObservedMaterials": [{"materialId": "hair.human", "status": "request-input"}],
            "regions": [{
                "componentId": "torso-armor",
                "regionId": "paint",
                "sourceImage": str(self.reference),
                "bbox": {"x": 64, "y": 64, "width": 384, "height": 384},
                "materialId": "coating.painted-metal",
                "materialSpecId": "armor-paint",
                "family": "coating",
                "subtype": "paint-over-metal",
                "finish": "gloss-or-satin",
            }],
        }, indent=2), encoding="utf-8")
        analysis = analyze_manifest(manifest, self.tmp / "analysis-with-unobserved")
        self.assertEqual(analysis["status"], "probe")
        self.assertEqual(len(analysis["unresolvedNotObservedMaterials"]), 1)
        spec = {"materials": [{"id": "armor-paint", "baseColor": "#20344A"}], "componentTree": []}
        spec = apply_material_analysis(spec, analysis, allow_probe=True)
        self.assertEqual(spec["materialPipeline"]["status"], "probe")


if __name__ == "__main__":
    unittest.main()
