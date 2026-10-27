"""Crash-safe Playwright receipt tests without an installed browser dependency."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from forge.stage4_review.render_bridge import init_manifest, write_manifest
from forge.tests.test_glb_reference import write_triangle_glb
from forge.tests.test_render_bridge import write_png
from scripts.capture_threejs_playwright import capture


class SimulatedPlaywrightTimeout(Exception):
    pass


class SimulatedPage:
    def __init__(self, *, fail_camera=None, fail_pass=None, fail_navigation=False):
        self.fail_camera = fail_camera
        self.fail_pass = fail_pass
        self.fail_navigation = fail_navigation
        self.captured = []

    def on(self, *args):
        return None

    def set_default_timeout(self, timeout):
        self.default_timeout = timeout

    def set_default_navigation_timeout(self, timeout):
        self.navigation_timeout = timeout

    def goto(self, *args, **kwargs):
        if self.fail_navigation:
            raise SimulatedPlaywrightTimeout("navigation timeout")

    def wait_for_function(self, *args, **kwargs):
        return None

    def evaluate(self, script, argument=None):
        if isinstance(argument, dict) and "timeoutMs" in argument:
            argument = argument["argument"]
        if "await api.setCamera(camera)" in script:
            if argument["id"] == self.fail_camera:
                raise SimulatedPlaywrightTimeout("synthetic second-view timeout")
            return {"ok": True}
        if "typeof window.__IMG2THREEJS_CAPTURE__" in script:
            return {"capturePass": True}
        if "await api.capturePass" in script:
            if argument["passId"] == self.fail_pass:
                raise SimulatedPlaywrightTimeout("synthetic diagnostic-pass timeout")
            return {"ok": True, "selector": "canvas"}
        if "await api.setReferenceMode" in script:
            return {"ok": True}
        if "requestAnimationFrame" in script:
            return None
        if "document.querySelector('canvas')" in script:
            return {"width": 16, "height": 16}
        if "__IMG2THREEJS_READY__" in script:
            return True
        raise AssertionError("unexpected browser evaluation: " + script[:100])

    def screenshot(self, *, path, **kwargs):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_png(target, 16, 16)
        self.captured.append(target)

    def locator(self, selector):
        if selector != "canvas":
            raise AssertionError("unexpected selector: " + selector)
        return self


class SimulatedBrowser:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_context(self, **kwargs):
        return self

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class SimulatedSession:
    def __init__(self, page):
        self.chromium = self
        self.browser = SimulatedBrowser(page)

    def launch(self, **kwargs):
        return self.browser

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class CaptureCheckpointTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.reference = self.root / "reference.png"
        write_png(self.reference)
        self.path = self.root / "manifest.json"
        self.manifest = init_manifest(
            self.reference, "http://127.0.0.1:5173", self.path,
            (620, 1000), 1.0, "captures",
        )
        write_manifest(self.path, self.manifest)

    def execute(self, page, *, mode="procedural", selected=None, resume=False):
        api = types.ModuleType("playwright.sync_api")
        api.Error = SimulatedPlaywrightTimeout
        session = SimulatedSession(page)
        api.sync_playwright = lambda: session
        package = types.ModuleType("playwright")
        package.sync_api = api
        with patch.dict(sys.modules, {"playwright": package, "playwright.sync_api": api}):
            return capture(self.path, selected or [], False, 500, mode, resume=resume)

    def saved(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_second_camera_timeout_preserves_first_screenshot_receipt(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic second-view timeout"):
            self.execute(SimulatedPage(fail_camera="orbit-plus35"))
        saved = self.saved()
        hero, second = saved["captures"][:2]
        self.assertEqual(hero["status"], "recorded")
        self.assertEqual(second["status"], "failed")
        self.assertFalse(second["captureReceipt"]["complete"])
        self.assertTrue(hero["captureReceipt"]["complete"])
        self.assertEqual(len(hero["screenshotSha256"]), 64)
        self.assertTrue((self.root / hero["path"]).is_file())
        self.assertEqual(hero["screenshotSha256"], hashlib.sha256((self.root / hero["path"]).read_bytes()).hexdigest())
        self.assertIs(hero["readySignal"], True)
        self.assertEqual(saved["evidence"]["browser"]["adapter"], "playwright")
        self.assertIn("synthetic second-view timeout", saved["evidence"]["lastCaptureError"])

    def test_reference_mode_checkpoint_survives_next_camera_failure(self):
        glb = self.root / "reference.glb"
        write_triangle_glb(glb)
        self.manifest = init_manifest(
            None, "http://127.0.0.1:5173", self.path, (620, 1000),
            1.0, "captures", reference_glb=glb,
            reference_browser_url="http://127.0.0.1:5173/reference.glb",
        )
        write_manifest(self.path, self.manifest)
        with self.assertRaisesRegex(RuntimeError, "synthetic second-view timeout"):
            self.execute(SimulatedPage(fail_camera="orbit-plus35"), mode="reference")
        saved = self.saved()
        reference = saved["captures"][0]["reference"]
        self.assertEqual(reference["status"], "recorded")
        self.assertTrue(reference["captureReceipt"]["complete"])
        self.assertEqual(reference["screenshotSha256"], hashlib.sha256((self.root / reference["path"]).read_bytes()).hexdigest())
        self.assertEqual(saved["captures"][0]["status"], "pending")
        self.assertEqual(saved["captures"][1]["reference"]["status"], "failed")
        self.assertFalse(saved["captures"][1]["reference"]["captureReceipt"]["complete"])

    def test_diagnostic_pass_timeout_preserves_completed_pass_receipts(self):
        profile = Path(__file__).resolve().parents[2] / "docs/specs/render-profile.v2.example.json"
        self.manifest = init_manifest(
            self.reference, "http://127.0.0.1:5173", self.path,
            (620, 1000), 1.0, "captures", render_profile=profile,
        )
        write_manifest(self.path, self.manifest)
        with self.assertRaisesRegex(RuntimeError, "synthetic diagnostic-pass timeout"):
            self.execute(SimulatedPage(fail_pass="depth"), selected=["hero"])
        hero = self.saved()["captures"][0]
        self.assertEqual(hero["status"], "failed")
        self.assertFalse(hero["captureReceipt"]["complete"])
        self.assertEqual(hero["screenshotSha256"], hashlib.sha256((self.root / hero["path"]).read_bytes()).hexdigest())
        self.assertEqual(hero["passes"]["beauty"]["status"], "recorded")
        self.assertEqual(hero["passes"]["alpha-silhouette"]["status"], "recorded")
        self.assertEqual(hero["passes"]["semantic-id"]["status"], "recorded")
        self.assertEqual(hero["passes"]["depth"]["status"], "pending")
        self.assertEqual(len(hero["passes"]["semantic-id"]["sha256"]), 64)
        for pass_id in ("beauty", "alpha-silhouette", "semantic-id"):
            record = hero["passes"][pass_id]
            self.assertTrue(record["captureReceipt"]["complete"])
            self.assertEqual(record["sha256"], hashlib.sha256((self.root / record["path"]).read_bytes()).hexdigest())

    def test_navigation_failure_records_error_without_faking_a_shot(self):
        with self.assertRaisesRegex(RuntimeError, "navigation timeout"):
            self.execute(SimulatedPage(fail_navigation=True))
        saved = self.saved()
        self.assertEqual(saved["captures"][0]["status"], "pending")
        self.assertIn("navigation timeout", saved["evidence"]["lastCaptureError"])

    def test_successful_retry_clears_stale_capture_error(self):
        self.manifest["evidence"]["lastCaptureError"] = "old failure"
        write_manifest(self.path, self.manifest)
        result = self.execute(SimulatedPage(), selected=["hero"])
        saved = self.saved()
        self.assertEqual(result["captured"], ["hero"])
        self.assertNotIn("lastCaptureError", saved["evidence"])
        self.assertEqual(saved["captures"][0]["status"], "recorded")
        self.assertEqual(saved["captures"][1]["status"], "pending")

    def test_resume_rejects_truthy_non_boolean_readiness(self):
        for ready_value in ("true", "false", 1, 1.0, -1):
            with self.subTest(ready_value=ready_value):
                self.execute(SimulatedPage(), selected=["hero"])
                manifest = self.saved()
                manifest["captures"][0]["readySignal"] = ready_value
                write_manifest(self.path, manifest)
                page = SimulatedPage()
                result = self.execute(page, selected=["hero"], resume=True)
                self.assertEqual(result["captured"], ["hero"])
                self.assertEqual(result["skipped"], [])
                self.assertEqual(len(page.captured), 1)
                self.assertIs(self.saved()["captures"][0]["readySignal"], True)


if __name__ == "__main__":
    unittest.main()
