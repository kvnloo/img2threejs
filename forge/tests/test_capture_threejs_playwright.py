"""Capture recovery regressions; the core suite does not need Playwright installed."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import struct
import sys
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from unittest import mock

from forge.stage4_review.render_bridge import PASS_IDS, init_manifest, read_manifest, validate_manifest, write_manifest
from scripts import capture_threejs_playwright as adapter


def write_png(path: Path, color: int = 100) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\x00" + bytes([color, 80, 80]) * 8) * 8))
        + chunk(b"IEND", b"")
    )


def write_glb(path: Path) -> None:
    positions = struct.pack("<9f", -1, 0, 0, 1, 0, 0, 0, 1, 0)
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "buffers": [{"byteLength": len(positions)}],
        "bufferViews": [{"buffer": 0, "byteLength": len(positions)}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}],
    }
    data = json.dumps(document).encode("utf-8")
    data += b" " * (-len(data) % 4)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 28 + len(data) + len(positions))
        + struct.pack("<II", len(data), 0x4E4F534A) + data
        + struct.pack("<II", len(positions), 0x004E4942) + positions
    )


class BrowserError(Exception):
    pass


class FakePage:
    """Implements only the public sync Playwright calls used by the adapter."""

    def __init__(self, *, fail=None, errors=(), late_errors=(), ready=True):
        self.fail = fail or {}
        self.errors = errors
        self.late_errors = late_errors
        self.ready = ready
        self.current_id = None
        self.current_pass = None
        self.handlers = {}
        self.actions = []
        self.evaluations = []
        self.screenshots = []
        self.default_timeout = None
        self.navigation_timeout = None
        self.closed = False
        self.launches = 0

    def on(self, event, handler):
        self.handlers[event] = handler

    def set_default_timeout(self, timeout):
        self.default_timeout = timeout

    def set_default_navigation_timeout(self, timeout):
        self.navigation_timeout = timeout

    def step(self, stage):
        self.actions.append((stage, self.current_id, self.current_pass))
        failure = self.fail.get((stage, self.current_id, self.current_pass), self.fail.get(stage))
        if isinstance(failure, BaseException):
            raise failure
        return failure

    def emit_errors(self, errors):
        for event, message in errors:
            value = types.SimpleNamespace(type="error", text=message) if event == "console" else message
            self.handlers[event](value)

    def goto(self, url, **kwargs):
        self.emit_errors(self.errors)
        self.step("navigation")

    def wait_for_function(self, expression, **kwargs):
        self.step("readiness")

    def evaluate(self, expression, argument=None):
        self.evaluations.append((expression, argument))
        payload = argument.get("argument") if isinstance(argument, dict) and "timeoutMs" in argument else argument
        if "setReferenceMode" in expression:
            return self.step("reference") or {"ok": True}
        if "setCamera" in expression:
            self.current_id = payload["id"]
            self.current_pass = None
            return self.step("camera") or {"ok": True}
        if "capturePass" in expression:
            if not isinstance(payload, dict) or "passId" not in payload:
                return {"capturePass": True}
            self.current_pass = payload["passId"]
            return self.step("pass") or {"ok": True, "selector": "canvas"}
        if "requestAnimationFrame" in expression:
            return self.step("frames")
        if "document.querySelector" in expression:
            return self.step("canvas") or {"width": 8, "height": 8}
        if "__IMG2THREEJS_READY__" in expression:
            self.step("ready-value")
            return self.ready
        raise AssertionError(f"unexpected browser evaluation: {expression}")

    def locator(self, selector):
        return self

    def screenshot(self, *, path, **kwargs):
        self.step("screenshot")
        self.screenshots.append((Path(path), kwargs))
        write_png(Path(path), color=100 + len(self.screenshots))

    def close(self):
        self.closed = True
        self.emit_errors(self.late_errors)
        self.step("close")


class FakePlaywright:
    def __init__(self, page):
        self.page = page
        self.chromium = self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def launch(self, **kwargs):
        self.page.launches += 1
        self.page.step("launch")
        return self

    def new_context(self, **kwargs):
        return self

    def new_page(self):
        return self.page

    def close(self):
        self.page.close()


class CaptureRecoveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest_path = self.root / "render-manifest.json"
        self.make_manifest()

    def make_manifest(self, *, glb=False, v2=False):
        reference = self.root / ("reference.glb" if glb else "reference.png")
        if glb:
            write_glb(reference)
        else:
            write_png(reference)
        manifest = init_manifest(
            None if glb else reference, "http://127.0.0.1:5173/#/fixture", self.manifest_path,
            (8, 8), 1.0, "captures", reference_glb=reference if glb else None,
            reference_browser_url="/reference.glb" if glb else None,
        )
        manifest["captures"] = manifest["captures"][:2]
        if v2:
            profile = self.root / "profile.json"
            profile.write_text('{"fixture": 1}', encoding="utf-8")
            manifest["fidelityTrack"] = "glb-mediated-v2"
            manifest["renderProfile"] = {"path": "profile.json", "sha256": hashlib.sha256(profile.read_bytes()).hexdigest()}
        write_manifest(self.manifest_path, manifest)
        return manifest

    def run_capture(self, page=None, *, ids=None, mode="procedural", resume=None, timeout=73):
        page = page or FakePage()
        sync_api = types.ModuleType("playwright.sync_api")
        sync_api.Error = BrowserError
        sync_api.sync_playwright = lambda: FakePlaywright(page)
        package = types.ModuleType("playwright")
        package.sync_api = sync_api
        kwargs = {} if resume is None else {"resume": resume}
        with mock.patch.dict(sys.modules, {"playwright": package, "playwright.sync_api": sync_api}):
            return adapter.capture(self.manifest_path, ids or [], False, timeout, mode, **kwargs)

    def saved(self):
        return read_manifest(self.manifest_path)

    def edit(self, change):
        manifest = self.saved()
        change(manifest)
        write_manifest(self.manifest_path, manifest)

    def assert_failed(self, message):
        session = self.saved()["evidence"]["captureSession"]
        self.assertEqual(session["status"], "failed")
        self.assertIn(message, str(session["error"]))

    def test_completed_view_is_saved_before_a_later_camera_failure(self):
        page = FakePage(fail={("camera", "orbit-plus35", None): BrowserError("second camera timed out")})
        with self.assertRaisesRegex(RuntimeError, "second camera timed out"):
            self.run_capture(page)
        hero, orbit = self.saved()["captures"]
        self.assertEqual(hero["status"], "recorded")
        self.assertEqual(hero["screenshotSha256"], hashlib.sha256((self.root / hero["path"]).read_bytes()).hexdigest())
        self.assertTrue(hero["captureReceipt"]["complete"])
        self.assertNotEqual(orbit["status"], "recorded")
        self.assert_failed("second camera timed out")
        self.assertTrue(page.closed)

    def test_readiness_timeout_persists_console_and_page_errors(self):
        page = FakePage(fail={"readiness": BrowserError("ready wait timed out")},
                        errors=(("console", "GLB load failed"), ("pageerror", "render crashed")))
        with self.assertRaisesRegex(RuntimeError, "ready wait timed out"):
            self.run_capture(page)
        self.assertEqual(self.saved()["evidence"]["consoleErrors"], ["GLB load failed", "render crashed"])
        self.assert_failed("ready wait timed out")
        self.assertTrue(page.closed)

    def test_contract_error_is_checkpointed_without_playwright_exception(self):
        page = FakePage(fail={"camera": {"ok": False, "reason": "setCamera is missing"}})
        with self.assertRaisesRegex(RuntimeError, "setCamera is missing"):
            self.run_capture(page)
        self.assert_failed("setCamera is missing")

    def test_screenshot_timeout_is_checkpointed(self):
        with self.assertRaisesRegex(RuntimeError, "screenshot timed out"):
            self.run_capture(FakePage(fail={"screenshot": BrowserError("screenshot timed out")}))
        self.assert_failed("screenshot timed out")
        self.assertNotEqual(self.saved()["captures"][0]["status"], "recorded")

    def test_browser_lifecycle_failure_is_checkpointed(self):
        for stage in ("launch", "close"):
            with self.subTest(stage=stage):
                self.make_manifest()
                with self.assertRaisesRegex(RuntimeError, "browser unavailable"):
                    self.run_capture(FakePage(fail={stage: BrowserError("browser unavailable")}))
                self.assert_failed("browser unavailable")
                if stage == "close":
                    for capture in self.saved()["captures"]:
                        self.assertEqual(capture["status"], "recorded")
                        self.assertTrue(capture["captureReceipt"]["complete"])

    def test_lost_readiness_preserves_image_hash_without_a_complete_receipt(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                self.make_manifest()
                page = FakePage(ready=False, fail={"ready-value": BrowserError("readiness query failed")} if raises else None)
                with self.assertRaisesRegex(RuntimeError, "readiness query failed" if raises else "became unready"):
                    self.run_capture(page, ids=["hero"])
                hero = self.saved()["captures"][0]
                self.assertEqual(hero["screenshotSha256"], hashlib.sha256((self.root / hero["path"]).read_bytes()).hexdigest())
                self.assertFalse(hero["captureReceipt"]["complete"])
                self.assertNotEqual(hero["status"], "recorded")
                self.assertFalse(hero["readySignal"])
                self.assertEqual(self.run_capture(ids=["hero"], resume=True)["captured"], ["hero"])

    def test_browser_errors_are_recorded_and_prevent_resume_reuse(self):
        for timing in ("errors", "late_errors"):
            with self.subTest(timing=timing):
                self.make_manifest()
                page = FakePage(**{timing: (("console", "shader compile failed"), ("pageerror", "uncaught render error"))})
                result = self.run_capture(page, ids=["hero"])
                errors = ["shader compile failed", "uncaught render error"]
                self.assertEqual(result["consoleErrors"], errors)
                hero = self.saved()["captures"][0]
                self.assertEqual(hero["consoleErrors"], errors)
                self.assertFalse(hero["captureReceipt"]["complete"])
                self.assertEqual(self.saved()["evidence"]["captureSession"]["status"], "failed")
                self.assertEqual(self.run_capture(ids=["hero"], resume=True)["captured"], ["hero"])

    def test_resume_skips_only_verified_completed_views(self):
        self.run_capture(ids=["hero"])
        hero = self.saved()["captures"][0]
        page = FakePage()
        result = self.run_capture(page, resume=True)
        self.assertEqual(result["captured"], ["orbit-plus35"])
        self.assertEqual(result["skipped"], ["hero"])
        self.assertEqual(self.saved()["captures"][0], hero)
        self.assertEqual([path.name for path, _ in page.screenshots], ["orbit-plus35.png"])

    def test_default_call_rerenders_previously_recorded_views(self):
        self.run_capture()
        page = FakePage()
        result = self.run_capture(page)
        self.assertEqual(result["captured"], ["hero", "orbit-plus35"])
        self.assertEqual(len(page.screenshots), 2)

    def test_resume_rerenders_legacy_records_without_a_receipt(self):
        self.run_capture(ids=["hero"])
        self.edit(lambda manifest: manifest["captures"][0].pop("captureReceipt", None))
        result = self.run_capture(ids=["hero"], resume=True)
        self.assertEqual(result["captured"], ["hero"])

    def test_resume_rerenders_missing_or_tampered_screenshot(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                self.run_capture(ids=["hero"])
                path = self.root / self.saved()["captures"][0]["path"]
                if missing:
                    path.unlink()
                else:
                    write_png(path, color=240)
                result = self.run_capture(ids=["hero"], resume=True)
                self.assertEqual(result["captured"], ["hero"])

    def test_resume_requires_ready_error_free_complete_record(self):
        changes = (
            lambda record: record.update(status="pending"),
            lambda record: record.update(readySignal=False),
            lambda record: record.update(consoleErrors=["uncaught error"]),
            lambda record: record["captureReceipt"].update(complete=False),
            lambda record: record.pop("screenshotSha256"),
        )
        for index, change in enumerate(changes):
            with self.subTest(change=index):
                self.run_capture(ids=["hero"])
                self.edit(lambda manifest: change(manifest["captures"][0]))
                self.assertEqual(self.run_capture(ids=["hero"], resume=True)["captured"], ["hero"])

    def test_resume_reprobes_image_receipt_even_when_saved_hash_matches(self):
        # This catches stale or forged metadata in a persisted receipt. An
        # intact hash is not evidence that its saved width/type describe bytes.
        for change in ("width", "height", "type", "missing", "nonobject", "corrupt-rehashed"):
            with self.subTest(change=change):
                self.make_manifest()
                self.run_capture(ids=["hero"])
                receipt = self.saved()
                image_record = receipt["captures"][0]
                if change == "missing":
                    image_record.pop("image")
                elif change == "nonobject":
                    image_record["image"] = "PNG"
                elif change == "corrupt-rehashed":
                    screenshot = self.root / image_record["path"]
                    screenshot.write_bytes(b"not an image")
                    image_record["screenshotSha256"] = hashlib.sha256(screenshot.read_bytes()).hexdigest()
                else:
                    image_record["image"][change] = (
                        12345 if change in {"width", "height"} else "JPEG"
                    )
                write_manifest(self.manifest_path, receipt)
                result = self.run_capture(ids=["hero"], resume=True)
                self.assertEqual(result["captured"], ["hero"])

    def test_resume_reprobes_glb_baseline_and_diagnostic_pass_receipts(self):
        for mode in ("reference", "diagnostic"):
            with self.subTest(mode=mode):
                self.make_manifest(glb=True, v2=True)
                browser_mode = "reference" if mode == "reference" else "procedural"
                self.run_capture(ids=["hero"], mode=browser_mode)
                manifest = self.saved()
                record = (manifest["captures"][0]["reference"] if mode == "reference"
                          else manifest["captures"][0]["passes"]["depth"])
                record["image"]["width"] = 999
                write_manifest(self.manifest_path, manifest)
                result = self.run_capture(ids=["hero"], mode=browser_mode, resume=True)
                self.assertEqual(result["captured"], ["hero"])

    def test_resume_rejects_missing_source_hash_provenance_even_when_recorded(self):
        for source_name in ("reference", "renderProfile"):
            with self.subTest(source=source_name):
                self.make_manifest(glb=True, v2=True)
                self.edit(lambda manifest: manifest[source_name].pop("sha256"))
                # The underlying capture can be taken, but it cannot later be
                # called safely reusable without declared source provenance.
                self.run_capture(ids=["hero"])
                result = self.run_capture(ids=["hero"], resume=True)
                self.assertEqual(result["captured"], ["hero"])

    def test_changed_camera_inputs_require_a_fresh_capture(self):
        for key, value in (("azimuthDegrees", 20), ("target", [1, 2, 3]), ("fovDegrees", 35)):
            with self.subTest(key=key):
                self.make_manifest()
                self.run_capture(ids=["hero"])
                self.edit(lambda manifest: manifest["captures"][0].update({key: value}))
                self.assertEqual(self.run_capture(ids=["hero"], resume=True)["captured"], ["hero"])

    def test_changed_runtime_inputs_require_a_fresh_capture(self):
        for key, value in (("url", "http://127.0.0.1:5173/#/changed"), ("viewport", [9, 8]),
                           ("devicePixelRatio", 2), ("renderer", "WebGPURenderer")):
            with self.subTest(key=key):
                self.make_manifest(glb=True)
                self.run_capture()
                self.run_capture(mode="reference")
                self.edit(lambda manifest: manifest["runtime"].update({key: value}))
                self.assertEqual(self.run_capture(ids=["hero"], resume=True)["captured"], ["hero"])
                hero, orbit = self.saved()["captures"]
                self.assertNotEqual(orbit["status"], "recorded")
                self.assertNotEqual(hero["reference"]["status"], "recorded")
                self.assertNotEqual(orbit["reference"]["status"], "recorded")
                self.assertFalse(validate_manifest(self.manifest_path, require_complete=True)["passed"])

    def test_changed_reference_metadata_or_file_requires_a_fresh_capture(self):
        for field in ("browserUrl", "sha256", "file", "missing-file"):
            with self.subTest(field=field):
                self.make_manifest(glb=True)
                self.run_capture(ids=["hero"], mode="reference")
                if field == "file":
                    with (self.root / "reference.glb").open("ab") as handle:
                        handle.write(b"changed")
                elif field == "missing-file":
                    (self.root / "reference.glb").unlink()
                else:
                    self.edit(lambda manifest: manifest["reference"].update({field: "changed"}))
                result = self.run_capture(ids=["hero"], mode="reference", resume=True)
                self.assertEqual(result["captured"], ["hero"])
                if field == "missing-file":
                    self.assertEqual(self.run_capture(ids=["hero"], mode="reference", resume=True)["captured"], ["hero"])

    def test_changed_render_profile_file_requires_a_fresh_capture(self):
        self.make_manifest(glb=True, v2=True)
        self.run_capture(ids=["hero"])
        (self.root / "profile.json").write_text('{"fixture": 2}', encoding="utf-8")
        self.assertEqual(self.run_capture(ids=["hero"], resume=True)["captured"], ["hero"])

    def test_reference_and_procedural_resume_are_independent(self):
        self.make_manifest(glb=True)
        self.run_capture(ids=["hero"], mode="reference")
        reference = self.saved()["captures"][0]["reference"]
        self.assertEqual(self.run_capture(ids=["hero"], resume=True)["captured"], ["hero"])
        result = self.run_capture(ids=["hero"], mode="reference", resume=True)
        self.assertEqual(result["skipped"], ["hero"])
        self.assertEqual(result["captured"], [])
        self.assertEqual(self.saved()["captures"][0]["reference"], reference)

    def test_v2_resume_requires_every_pass_and_hash(self):
        for change in ("missing-file", "tampered-file", "missing-hash", "pending"):
            with self.subTest(change=change):
                self.make_manifest(glb=True, v2=True)
                self.run_capture(ids=["hero"])
                manifest = self.saved()
                record = manifest["captures"][0]["passes"]["depth"]
                if change == "missing-file":
                    (self.root / record["path"]).unlink()
                elif change == "tampered-file":
                    write_png(self.root / record["path"], color=240)
                elif change == "missing-hash":
                    record.pop("sha256")
                else:
                    record["status"] = "pending"
                write_manifest(self.manifest_path, manifest)
                result = self.run_capture(ids=["hero"], resume=True)
                self.assertEqual(result["captured"], ["hero"])
                self.assertEqual(set(self.saved()["captures"][0]["passes"]), set(PASS_IDS))

    def test_interrupted_v2_pass_preserves_completed_pass_hashes(self):
        self.make_manifest(glb=True, v2=True)
        page = FakePage(fail={("pass", "hero", "semantic-id"): BrowserError("semantic pass timed out")})
        with self.assertRaisesRegex(RuntimeError, "semantic pass timed out"):
            self.run_capture(page, ids=["hero"])
        hero = self.saved()["captures"][0]
        self.assertEqual(hero["passes"]["beauty"]["status"], "recorded")
        self.assertEqual(hero["passes"]["alpha-silhouette"]["status"], "recorded")
        self.assertNotEqual(hero["passes"]["semantic-id"]["status"], "recorded")
        self.assertFalse(hero["captureReceipt"]["complete"])
        self.assert_failed("semantic pass timed out")
        self.assertEqual(self.run_capture(ids=["hero"], resume=True)["captured"], ["hero"])

    def test_v2_reference_pass_completion_does_not_require_procedural_passes(self):
        self.make_manifest(glb=True, v2=True)
        self.run_capture(ids=["hero"], mode="reference")
        result = self.run_capture(ids=["hero"], mode="reference", resume=True)
        self.assertEqual(result["captured"], [])
        self.assertEqual(result["skipped"], ["hero"])
        self.assertEqual(self.saved()["captures"][0]["status"], "pending")

    def test_failed_rerender_invalidates_old_selected_views_and_passes(self):
        self.make_manifest(glb=True, v2=True)
        self.run_capture()
        with self.assertRaisesRegex(RuntimeError, "navigation failed"):
            self.run_capture(FakePage(fail={"navigation": BrowserError("navigation failed")}))
        for capture in self.saved()["captures"]:
            self.assertNotEqual(capture["status"], "recorded")
            self.assertNotIn("screenshotSha256", capture)
            for record in capture["passes"].values():
                self.assertNotEqual(record["status"], "recorded")
                self.assertNotIn("sha256", record)

    def test_failed_resume_preserves_the_skipped_view(self):
        self.run_capture(ids=["hero"])
        hero = self.saved()["captures"][0]
        with self.assertRaisesRegex(RuntimeError, "navigation failed"):
            self.run_capture(FakePage(fail={"navigation": BrowserError("navigation failed")}), resume=True)
        self.assertEqual(self.saved()["captures"][0], hero)
        self.assert_failed("navigation failed")

    def test_invalid_capture_id_or_timeout_is_rejected_before_browser_start(self):
        for kwargs in ({"ids": ["hero", "missing"]}, {"timeout": 0}, {"timeout": -1}):
            with self.subTest(kwargs=kwargs):
                page = FakePage()
                with self.assertRaises(ValueError):
                    self.run_capture(page, **kwargs)
                self.assertEqual(page.launches, 0)

    def test_all_async_contracts_and_screenshots_use_the_requested_timeout(self):
        self.make_manifest(glb=True, v2=True)
        page = FakePage()
        self.run_capture(page, ids=["hero"], mode="reference", timeout=73)
        self.assertEqual(page.default_timeout, 73)
        self.assertEqual(page.navigation_timeout, 73)
        for marker in ("setReferenceMode", "setCamera", "capturePass", "requestAnimationFrame"):
            calls = [(expression, payload) for expression, payload in page.evaluations
                     if marker in expression and isinstance(payload, dict)]
            self.assertTrue(calls, marker)
            for expression, payload in calls:
                self.assertEqual(payload["timeoutMs"], 73)
                self.assertIn("Promise.race", expression)
                self.assertIn("setTimeout", expression)
                self.assertIn("clearTimeout", expression)
        self.assertTrue(page.screenshots)
        for _, kwargs in page.screenshots:
            self.assertEqual(kwargs["timeout"], 73)

    def test_cli_passes_resume_to_capture(self):
        result = {"captured": [], "skipped": ["hero"], "consoleErrors": []}
        with mock.patch.object(adapter, "capture", return_value=result) as capture_mock, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(adapter.main(["--manifest", str(self.manifest_path), "--resume"]), 0)
        self.assertTrue(capture_mock.call_args.kwargs["resume"])


if __name__ == "__main__":
    unittest.main()
