#!/usr/bin/env python3
"""Optional Playwright adapter for the Python↔Three.js render bridge.

The target page must expose:

    window.__IMG2THREEJS_READY__ = true
    window.__IMG2THREEJS_CAPTURE__.setCamera(cameraSpec)

The adapter captures the actual browser canvas/viewport. It never renders a
replacement scene in Python and fails closed when the runtime contract is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forge.stage4_review.render_bridge import (  # noqa: E402
    find_capture,
    manifest_path,
    read_manifest,
    record_capture,
    record_capture_pass,
    record_reference_capture,
    now_utc,
    probe,
    sha256,
    PASS_IDS,
    write_manifest,
)


# These are evidence/output fields, not inputs to the camera contract. Excluding
# them keeps a receipt stable when recording screenshots mutates the manifest.
_CAPTURE_OUTPUT_FIELDS = {
    "path", "status", "recordedAt", "readySignal", "screenshotSha256", "image",
    "consoleErrors", "browserSnapshot", "passes", "reference", "captureReceipt",
}


def _capture_signature(manifest_path_value: Path, manifest: dict, capture_spec: dict, mode: str) -> str:
    sources = {}
    for name in ("reference", "renderProfile"):
        record = manifest.get(name)
        file_hash = None
        if isinstance(record, dict) and record.get("path"):
            source = manifest_path(manifest_path_value, str(record["path"]))
            try:
                file_hash = sha256(source)
            except OSError:
                pass
        # Keep declared provenance as well as the current file hash. A changed
        # file must not silently rebaseline the manifest's declared sha256.
        sources[name] = {"record": record, "fileSha256": file_hash}
    inputs = {
        "version": 1,
        "mode": mode,
        "runtime": manifest.get("runtime"),
        "fidelityTrack": manifest.get("fidelityTrack"),
        "camera": {key: value for key, value in capture_spec.items() if key not in _CAPTURE_OUTPUT_FIELDS},
        "sources": sources,
    }
    encoded = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _record_is_reusable(manifest_path_value: Path, record: dict, signature: str, hash_key: str) -> bool:
    receipt = record.get("captureReceipt", {})
    if (
        record.get("status") != "recorded"
        or record.get("readySignal") is not True
        or record.get("consoleErrors") != []
        or not isinstance(receipt, dict)
        or receipt.get("version") != 1
        or receipt.get("inputSignature") != signature
        or receipt.get("complete") is not True
        or not isinstance(record.get("path"), str)
        or not record["path"].strip()
        or not isinstance(record.get(hash_key), str)
        or len(record[hash_key]) != 64
        or any(ch not in "0123456789abcdef" for ch in record[hash_key])
    ):
        return False
    saved_image = record.get("image")
    if not isinstance(saved_image, dict) or not all(
        saved_image.get(field) for field in ("type", "width", "height")
    ):
        return False
    try:
        screenshot = manifest_path(manifest_path_value, record["path"])
        if sha256(screenshot) != record[hash_key]:
            return False
        # A current screenshot hash alone is insufficient if the record was
        # copied/relabelled, or if a damaged image was mistakenly rehashed.
        # Re-read its actual dimensions and type for every reuse decision.
        inspected = probe(screenshot)
        return all(
            inspected.get(field) == saved_image.get(field)
            for field in ("type", "width", "height")
        ) and bool(inspected.get("type") and inspected.get("width") and inspected.get("height"))
    except (OSError, ValueError, TypeError):
        return False


def _can_resume_capture(manifest_path_value: Path, manifest: dict, capture_spec: dict, mode: str) -> bool:
    target = capture_spec.get("reference") if mode == "reference" else capture_spec
    if not isinstance(target, dict):
        return False
    sources = ("reference", "renderProfile") if manifest.get("fidelityTrack") == "glb-mediated-v2" else ("reference",)
    for name in sources:
        source = manifest.get(name)
        if not isinstance(source, dict):
            return False
        path = source.get("path")
        declared_hash = source.get("sha256")
        if (
            not isinstance(path, str) or not path.strip()
            or not isinstance(declared_hash, str)
            or len(declared_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in declared_hash)
        ):
            return False
        try:
            if sha256(manifest_path(manifest_path_value, path)) != declared_hash:
                return False
        except (OSError, ValueError, TypeError):
            return False
    signature = _capture_signature(manifest_path_value, manifest, capture_spec, mode)
    if not _record_is_reusable(manifest_path_value, target, signature, "screenshotSha256"):
        return False
    if manifest.get("fidelityTrack") == "glb-mediated-v2":
        passes = target.get("passes")
        if not isinstance(passes, dict):
            return False
        for pass_id in PASS_IDS:
            record = passes.get(pass_id)
            if not isinstance(record, dict) or not _record_is_reusable(manifest_path_value, record, signature, "sha256"):
                return False
    return True


def _invalidate_capture(target: dict) -> None:
    target["status"] = "pending"
    for key in _CAPTURE_OUTPUT_FIELDS - {"path", "status", "passes", "reference"}:
        target.pop(key, None)
    passes = target.get("passes")
    for record in passes.values() if isinstance(passes, dict) else ():
        if isinstance(record, dict):
            record["status"] = "pending"
            for key in ("recordedAt", "sha256", "image", "readySignal", "consoleErrors", "captureReceipt"):
                record.pop(key, None)


def _evaluate_with_timeout(page, expression: str, argument, timeout_ms: int):
    """Bound async page hooks; Playwright's default timeout does not bound evaluate."""
    return page.evaluate(
        """async ({argument, timeoutMs}) => {
          let timer;
          try {
            return await Promise.race([
              Promise.resolve().then(() => (""" + expression + """)(argument)),
              new Promise((_, reject) => {
                timer = setTimeout(() => reject(new Error(
                  'Capture contract timed out after ' + timeoutMs + 'ms'
                )), timeoutMs);
              }),
            ]);
          } finally {
            clearTimeout(timer);
          }
        }""",
        {"argument": argument, "timeoutMs": timeout_ms},
    )


def capture(
    manifest_path_value: Path,
    capture_ids: list[str],
    headed: bool,
    timeout_ms: int,
    mode: str,
    resume: bool = False,
) -> dict:
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be greater than zero")
    if mode not in ("procedural", "reference"):
        raise ValueError(f"unknown capture mode: {mode}")
    manifest = read_manifest(manifest_path_value)
    runtime = manifest.get("runtime", {})
    viewport = runtime.get("viewport", [620, 1000])
    dpr = float(runtime.get("devicePixelRatio", 1))
    url = str(runtime.get("url", ""))
    if not url:
        raise ValueError("manifest runtime.url is missing")
    reference = manifest.get("reference", {})
    fidelity_v2 = manifest.get("fidelityTrack") == "glb-mediated-v2"
    if mode == "reference":
        if reference.get("kind") != "glb":
            raise ValueError("--mode reference requires a GLB reference manifest")
        if not reference.get("browserUrl"):
            raise ValueError("GLB reference manifest needs reference.browserUrl for the browser adapter")
    selected = list(dict.fromkeys(capture_ids or [str(item["id"]) for item in manifest.get("captures", [])]))
    if not selected:
        raise ValueError("manifest captures must contain at least one view")
    # Resolve the entire selection before importing/starting the browser or
    # invalidating receipts. A misspelled later id must not capture earlier ids.
    specs = {capture_id: find_capture(manifest, capture_id) for capture_id in selected}
    for capture_id, capture_spec in specs.items():
        target = capture_spec.get("reference") if mode == "reference" else capture_spec
        if not isinstance(target, dict) or not target.get("path"):
            raise ValueError(f"capture {capture_id} has no {mode} screenshot path")
        if fidelity_v2:
            passes = target.get("passes")
            if not isinstance(passes, dict) or any(
                not isinstance(passes.get(pass_id), dict) or not passes[pass_id].get("path")
                for pass_id in PASS_IDS
            ):
                raise ValueError(f"capture {capture_id} has an incomplete diagnostic pass plan")
    # A subset capture after a shared input change must not leave other views
    # looking current to consumers that only know the original status fields.
    # Only invalidate receipts owned by this adapter; older/manual records do
    # not contain enough provenance to establish an input mismatch here.
    for capture_spec in manifest.get("captures", []):
        if not isinstance(capture_spec, dict):
            continue
        for receipt_mode in ("procedural", "reference"):
            target = capture_spec.get("reference") if receipt_mode == "reference" else capture_spec
            previous = target.get("captureReceipt") if isinstance(target, dict) else None
            if isinstance(previous, dict) and previous.get("version") == 1:
                signature = _capture_signature(manifest_path_value, manifest, capture_spec, receipt_mode)
                if previous.get("inputSignature") != signature:
                    _invalidate_capture(target)
    skipped = [capture_id for capture_id in selected if resume and _can_resume_capture(
        manifest_path_value, manifest, specs[capture_id], mode
    )]
    pending = [capture_id for capture_id in selected if capture_id not in skipped]
    signatures = {
        capture_id: _capture_signature(manifest_path_value, manifest, specs[capture_id], mode)
        for capture_id in pending
    }
    for capture_id in pending:
        target = specs[capture_id].get("reference") if mode == "reference" else specs[capture_id]
        _invalidate_capture(target)
    console_errors: list[str] = []
    page_errors: list[str] = []
    browser_info: dict = manifest.get("evidence", {}).get("browser") or {}
    captured: list[str] = []
    session = {
        "status": "running", "startedAt": now_utc(), "mode": mode,
        "captured": captured, "skipped": skipped, "captureId": None,
        "passId": None, "stage": "setup", "readySignal": None,
    }

    def checkpoint() -> None:
        evidence = manifest.setdefault("evidence", {})
        evidence["browser"] = browser_info
        evidence["consoleErrors"] = console_errors + page_errors
        evidence["captureSession"] = session
        if session["status"] == "failed":
            error = session["error"]
            evidence["lastCaptureError"] = f"{error['type']}: {error['message']}"
        elif session["status"] == "complete":
            evidence.pop("lastCaptureError", None)
        write_manifest(manifest_path_value, manifest)

    def receipt(signature: str, complete: bool) -> dict:
        return {"version": 1, "inputSignature": signature, "complete": complete}

    checkpoint()
    playwright_error = ()
    try:
        if pending:
            try:
                from playwright.sync_api import Error as PlaywrightError  # type: ignore[import-not-found]
                from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError(
                    "Playwright is not installed. Install it in an isolated environment "
                    "(`python3 -m pip install playwright` and `playwright install chromium`) "
                    "or use the existing Chrome DevTools MCP adapter."
                ) from exc
            playwright_error = PlaywrightError
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=not headed)
                browser_info = {"adapter": "playwright", "browser": "chromium", "headless": not headed}
                try:
                    context = browser.new_context(
                        viewport={"width": int(viewport[0]), "height": int(viewport[1])},
                        device_scale_factor=dpr,
                    )
                    page = context.new_page()
                    page.set_default_timeout(timeout_ms)
                    page.set_default_navigation_timeout(timeout_ms)
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
                    session["stage"] = "navigation"
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    session["stage"] = "readiness"
                    page.wait_for_function("() => window.__IMG2THREEJS_READY__ === true", timeout=timeout_ms)
                    session["readySignal"] = True

                    def evaluate(expression: str, argument=None):
                        return _evaluate_with_timeout(page, expression, argument, timeout_ms)

                    if fidelity_v2:
                        session["stage"] = "pass-contract"
                        pass_contract = evaluate(
                            "() => ({capturePass: typeof window.__IMG2THREEJS_CAPTURE__?.capturePass === 'function'})"
                        )
                        if not pass_contract.get("capturePass"):
                            raise RuntimeError(
                                "GLB-mediated-v2 route must expose "
                                "window.__IMG2THREEJS_CAPTURE__.capturePass({passId, mode})"
                            )
                    session["stage"] = "reference-mode"
                    mode_result = evaluate(
                        """async ({mode, reference}) => {
                          const api = window.__IMG2THREEJS_CAPTURE__;
                          if (mode !== 'reference') return {ok: true};
                          if (!api || typeof api.setReferenceMode !== 'function') {
                            return {ok: false, reason: 'window.__IMG2THREEJS_CAPTURE__.setReferenceMode is missing'};
                          }
                          await api.setReferenceMode({kind: 'glb', url: reference.browserUrl});
                          return {ok: true};
                        }""",
                        {"mode": mode, "reference": reference},
                    )
                    if not mode_result.get("ok"):
                        raise RuntimeError(str(mode_result.get("reason", "reference mode contract failed")))

                    for capture_id in pending:
                        capture_spec = specs[capture_id]
                        target = capture_spec.get("reference") if mode == "reference" else capture_spec
                        signature = signatures[capture_id]
                        session.update({"captureId": capture_id, "passId": None, "stage": "camera"})
                        result = evaluate(
                            """async (camera) => {
                              const api = window.__IMG2THREEJS_CAPTURE__;
                              if (!api || typeof api.setCamera !== 'function') {
                                return {ok: false, reason: 'window.__IMG2THREEJS_CAPTURE__.setCamera is missing'};
                              }
                              await api.setCamera(camera);
                              return {ok: true};
                            }""",
                            capture_spec,
                        )
                        if not result.get("ok"):
                            raise RuntimeError(str(result.get("reason", "camera contract failed")))
                        session["stage"] = "frames"
                        evaluate(
                            """async (frames) => {
                              for (let i = 0; i < frames; i += 1) {
                                await new Promise((resolve) => requestAnimationFrame(resolve));
                              }
                            }""",
                            2,
                        )
                        canvas = evaluate(
                            """() => {
                              const canvas = document.querySelector('canvas');
                              return canvas ? {width: canvas.width, height: canvas.height} : null;
                            }"""
                        )
                        if not canvas or canvas["width"] <= 0 or canvas["height"] <= 0:
                            raise RuntimeError("Three.js canvas has zero dimensions")
                        screenshot = manifest_path(manifest_path_value, str(target["path"]))
                        screenshot.parent.mkdir(parents=True, exist_ok=True)
                        pass_ids = PASS_IDS if fidelity_v2 else ("beauty",)
                        for pass_id in pass_ids:
                            session.update({"passId": pass_id, "stage": "pass" if fidelity_v2 else "screenshot"})
                            pass_path = screenshot if pass_id == "beauty" else manifest_path(
                                manifest_path_value, str(target["passes"][pass_id]["path"])
                            )
                            pass_path.parent.mkdir(parents=True, exist_ok=True)
                            if fidelity_v2:
                                pass_result = evaluate(
                                    """async ({passId, mode}) => {
                                      const api = window.__IMG2THREEJS_CAPTURE__;
                                      const result = await api.capturePass({passId, mode});
                                      return result || {ok: true};
                                    }""",
                                    {"passId": pass_id, "mode": mode},
                                )
                                if pass_result.get("ok") is False:
                                    raise RuntimeError(str(pass_result.get("reason", "diagnostic pass failed")))
                                selector = str(pass_result.get("selector", "canvas"))
                                session["stage"] = "screenshot"
                                page.locator(selector).screenshot(path=str(pass_path), timeout=timeout_ms)
                            else:
                                page.screenshot(path=str(pass_path), full_page=False, timeout=timeout_ms)
                            ready_value = None
                            try:
                                session["stage"] = "capture-readiness"
                                ready_value = evaluate("() => window.__IMG2THREEJS_READY__ === true")
                            finally:
                                # A saved image is checkpointed even if the
                                # subsequent readiness query itself fails.
                                session["readySignal"] = ready_value
                                errors = console_errors + page_errors
                                valid = ready_value is True and not errors
                                if pass_id == "beauty":
                                    if mode == "reference":
                                        record_reference_capture(
                                            manifest_path_value, manifest, capture_id, screenshot,
                                            ready_signal=ready_value, console_errors=errors,
                                        )
                                    else:
                                        record_capture(
                                            manifest_path_value, manifest, capture_id, screenshot,
                                            ready_signal=ready_value, console_errors=errors,
                                            browser_snapshot={"canvas": canvas},
                                        )
                                    target["captureReceipt"] = receipt(signature, valid and not fidelity_v2)
                                    checkpoint()
                                if fidelity_v2:
                                    record = record_capture_pass(
                                        manifest_path_value, manifest, capture_id, pass_id, pass_path,
                                        reference=mode == "reference",
                                    )
                                    record.update({
                                        "readySignal": ready_value, "consoleErrors": errors,
                                        "captureReceipt": receipt(signature, valid),
                                    })
                                    # Existing validators inspect the view's
                                    # errors, so failures in a later pass must
                                    # also invalidate the beauty-level record.
                                    target["consoleErrors"] = errors
                                    checkpoint()
                            if ready_value is not True:
                                raise RuntimeError("Three.js runtime became unready during capture")
                        if fidelity_v2:
                            target["captureReceipt"] = receipt(signature, not (console_errors + page_errors))
                        captured.append(capture_id)
                        session.update({"captureId": None, "passId": None, "stage": "between-captures"})
                        checkpoint()
                finally:
                    failing = sys.exc_info()[0] is not None
                    console_count, page_count = len(console_errors), len(page_errors)
                    try:
                        browser.close()
                    except Exception as close_error:
                        if not failing:
                            session["stage"] = "browser-close"
                            raise
                        session["browserCloseError"] = str(close_error)
                    finally:
                        late_errors = console_errors[console_count:] + page_errors[page_count:]
                        if late_errors:
                            # Playwright may deliver queued page/console events
                            # while closing. Keep a later resume from erasing
                            # those failures by skipping every fresh receipt.
                            for captured_id in captured:
                                target = specs[captured_id].get("reference") if mode == "reference" else specs[captured_id]
                                target["consoleErrors"] = target.get("consoleErrors", []) + late_errors
                                target["captureReceipt"]["complete"] = False
        session.update({
            "status": "failed" if console_errors or page_errors else "complete",
            "finishedAt": now_utc(), "captureId": None, "passId": None, "stage": "complete",
        })
        if console_errors or page_errors:
            session["error"] = {"type": "ConsoleError", "message": "Browser reported console or page errors"}
        checkpoint()
    except BaseException as exc:
        session.update({
            "status": "failed", "finishedAt": now_utc(),
            "error": {"type": type(exc).__name__, "message": str(exc) or type(exc).__name__},
        })
        capture_id = session.get("captureId")
        if capture_id is not None:
            target = specs[capture_id].get("reference") if mode == "reference" else specs[capture_id]
            target["status"] = "failed"
            target["captureReceipt"] = receipt(signatures[capture_id], False)
            target["readySignal"] = session["readySignal"]
            target["consoleErrors"] = console_errors + page_errors
        checkpoint()
        if isinstance(exc, playwright_error):
            raise RuntimeError(f"Playwright capture failed: {exc}") from exc
        raise
    return {
        "captured": captured, "skipped": skipped, "mode": mode,
        "browser": browser_info, "consoleErrors": console_errors + page_errors,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--capture-id", action="append", default=[], help="capture only this id; repeatable")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--mode", choices=("procedural", "reference"), default="procedural")
    parser.add_argument("--resume", action="store_true", help="reuse complete captures whose inputs and image hashes still match")
    args = parser.parse_args(argv)
    try:
        result = capture(args.manifest.expanduser().resolve(), args.capture_id, args.headed, args.timeout_ms, args.mode, resume=args.resume)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if not result["consoleErrors"] else 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
