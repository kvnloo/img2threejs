#!/usr/bin/env python3
"""Opt-in Chromium/Three.js regression for interrupted capture recovery.

Install Playwright and Chromium outside the stdlib core. Supply an installed
Three.js package with --three-root; this runner never downloads dependencies.
The procedural fixture tests capture mechanics, not reference reconstruction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forge.stage4_review.render_bridge import init_manifest, validate_manifest, write_manifest  # noqa: E402
from forge.stage1_intake.probe_image import probe  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_reference(path: Path) -> None:
    """Small original test input; it is not a reconstruction reference oracle."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))

    rows = b''.join(b'\0' + bytes([32, 56, 80]) * 16 for _ in range(16))
    path.write_bytes(
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', 16, 16, 8, 2, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')
    )


def run(three_root: Path, output: Path, timeout_ms: int) -> dict:
    require(timeout_ms > 0, '--timeout-ms must be positive')
    require((three_root / 'build/three.module.js').is_file(), '--three-root must point to the installed three package')
    package = json.loads((three_root / 'package.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=False)
    fixture = (ROOT / 'forge/tests/fixtures/capture_resume.html').read_bytes()
    reference = output / 'reference.png'
    write_reference(reference)
    faults: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            route = urlsplit(self.path).path
            if route == '/':
                data, mime = fixture, 'text/html; charset=utf-8'
            elif route == '/faults.json':
                data, mime = json.dumps(faults).encode(), 'application/json'
            elif route in ('/three/build/three.module.js', '/three/build/three.core.js'):
                data = (three_root / route.removeprefix('/three/')).read_bytes()
                mime = 'text/javascript; charset=utf-8'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args) -> None:
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/'
    adapter = ROOT / 'scripts/capture_threejs_playwright.py'
    checks: list[dict] = []

    def new_manifest(name: str, views: int = 2) -> Path:
        path = output / name / 'manifest.json'
        manifest = init_manifest(reference, url, path, (640, 480), 1.0, 'captures')
        manifest['captures'] = manifest['captures'][:views]
        manifest['runtime'].update({'buildId': 'capture-recovery-fixture-v1', 'threeVersion': package['version']})
        write_manifest(path, manifest)
        return path

    def invoke(path: Path, name: str, resume: bool = False) -> subprocess.CompletedProcess:
        command = [sys.executable, str(adapter), '--manifest', str(path), '--timeout-ms', str(timeout_ms)]
        if resume:
            command.append('--resume')
        start = time.monotonic()
        # A separate process watchdog also catches a regression to unbounded
        # evaluate(); the adapter's per-operation timer cannot stop blocked JS.
        process = subprocess.Popen(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=os.name == 'posix',
        )
        expired = False
        try:
            stdout, stderr = process.communicate(timeout=max(20, 4 * timeout_ms / 1000 + 10))
        except subprocess.TimeoutExpired:
            expired = True
            if os.name == 'posix':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif os.name == 'nt':
                # Stop this fixture's process tree, including the browser driver.
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                    capture_output=True, timeout=5, check=False,
                )
            else:
                process.kill()
            stdout, stderr = process.communicate(timeout=5)
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        elapsed = time.monotonic() - start
        (output / f'{name}.log').write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
        checks.append({
            'name': name, 'exitCode': result.returncode, 'elapsedSeconds': round(elapsed, 3),
            'watchdogExpired': expired,
        })
        if expired:
            (output / 'result.json').write_text(json.dumps({'passed': False, 'checks': checks}, indent=2) + '\n', encoding='utf-8')
            raise RuntimeError(f'{name}: capture exceeded the process watchdog; logs saved in {output}')
        return result

    def saved(path: Path) -> dict:
        return json.loads(path.read_text(encoding='utf-8'))

    try:
        manifest_path = new_manifest('recovery')
        faults['hangCaptureId'] = 'orbit-plus35'
        interrupted = invoke(manifest_path, 'interrupted')
        require(interrupted.returncode == 2, f'expected camera timeout, got {interrupted.stderr}')
        before = saved(manifest_path)
        hero = before['captures'][0]
        require(hero['status'] == 'recorded', 'completed hero receipt was lost on later timeout')
        require(hero['captureReceipt']['complete'], 'completed hero receipt is not reusable')
        require(before['captures'][1]['status'] == 'failed', 'interrupted view was not marked failed')
        session = before['evidence']['captureSession']
        require(session['stage'] == 'camera' and session['captureId'] == 'orbit-plus35', 'failure did not identify camera/view')
        require('timed out' in session['error']['message'], 'camera timeout was not persisted')
        hero_path = manifest_path.parent / hero['path']
        hero_hash, hero_mtime = digest(hero_path), hero_path.stat().st_mtime_ns
        require(hero_hash == hero['screenshotSha256'], 'hero PNG hash does not match receipt')
        shutil.copyfile(manifest_path, manifest_path.parent / 'interrupted-manifest.json')

        faults.clear()
        resumed = invoke(manifest_path, 'resumed', resume=True)
        require(resumed.returncode == 0, f'resume failed: {resumed.stderr}')
        result = json.loads(resumed.stdout)
        require(result['captured'] == ['orbit-plus35'] and result['skipped'] == ['hero'], 'resume repeated completed work')
        require(digest(hero_path) == hero_hash and hero_path.stat().st_mtime_ns == hero_mtime, 'resume overwrote the completed hero PNG')
        validation = validate_manifest(manifest_path, require_complete=True)
        require(validation['passed'], f'complete manifest invalid: {validation}')
        after = saved(manifest_path)
        orbit_path = manifest_path.parent / after['captures'][1]['path']
        require(digest(orbit_path) != hero_hash, 'different cameras produced identical screenshots')
        for image_path in (hero_path, orbit_path):
            image = probe(image_path)
            require((image['width'], image['height']) == (640, 480), 'unexpected browser screenshot dimensions')
        shutil.copyfile(manifest_path, manifest_path.parent / 'resumed-manifest.json')

        again = invoke(manifest_path, 'already-complete', resume=True)
        require(again.returncode == 0 and json.loads(again.stdout)['captured'] == [], 'complete resume did not skip all views')
        hero_path.write_bytes(hero_path.read_bytes() + b'changed fixture bytes')
        repaired = invoke(manifest_path, 'tampered-png', resume=True)
        require(repaired.returncode == 0, f'tampered PNG recovery failed: {repaired.stderr}')
        require(json.loads(repaired.stdout)['captured'] == ['hero'], 'tampered PNG was incorrectly reused')
        require(digest(hero_path) == hero_hash, 'recaptured hero differs from unchanged deterministic scene')

        # Mutating only the persisted image metadata leaves both file bytes and
        # SHA-256 intact. Resume must still re-render the mismatched receipt.
        amended = saved(manifest_path)
        amended['captures'][0]['image']['width'] = 123
        write_manifest(manifest_path, amended)
        stale_receipt = invoke(manifest_path, 'stale-image-receipt', resume=True)
        require(stale_receipt.returncode == 0, f'image receipt recovery failed: {stale_receipt.stderr}')
        resumed_ids = json.loads(stale_receipt.stdout)
        require(resumed_ids['captured'] == ['hero'] and resumed_ids['skipped'] == ['orbit-plus35'],
                'browser resume skipped a mismatched PNG dimension receipt')
        require(digest(hero_path) == hero_hash, 'image receipt recovery changed deterministic hero pixels')
        require(saved(manifest_path)['captures'][0]['image']['width'] == 640,
                'recapture did not restore measured PNG dimensions')

        unready_path = new_manifest('unready', views=1)
        faults.update({'ready': False, 'consoleError': 'fixture loader error', 'pageError': 'fixture runtime error'})
        unready = invoke(unready_path, 'readiness-failure')
        require(unready.returncode == 2, 'unready page did not fail')
        unready_manifest = saved(unready_path)
        require(unready_manifest['evidence']['captureSession']['stage'] == 'readiness', 'readiness failure stage lost')
        errors = unready_manifest['evidence']['consoleErrors']
        require(any('fixture loader error' in error for error in errors), 'console error was not persisted')
        require(any('fixture runtime error' in error for error in errors), 'page error was not persisted')
        require(unready_manifest['captures'][0]['status'] != 'recorded', 'unready page produced accepted evidence')

        lost_ready_path = new_manifest('lost-readiness', views=1)
        faults.clear()
        faults['dropReadyOnCapture'] = True
        lost_ready = invoke(lost_ready_path, 'readiness-lost-after-shot')
        require(lost_ready.returncode == 2, 'readiness loss after screenshot did not fail')
        lost_capture = saved(lost_ready_path)['captures'][0]
        require(lost_capture['status'] == 'failed' and lost_capture['readySignal'] is False, 'readiness loss incorrectly accepted')
        require(lost_capture.get('screenshotSha256'), 'saved screenshot hash was lost after readiness failure')

        report = {
            'passed': True, 'threeVersion': package['version'], 'pythonVersion': sys.version.split()[0],
            'fixtureSha256': hashlib.sha256(fixture).hexdigest(), 'adapterSha256': digest(adapter),
            'scope': 'Real Chromium/Three.js capture recovery; no reconstruction-fidelity claim.',
            'checks': checks, 'heroSha256': hero_hash, 'orbitSha256': digest(orbit_path),
            'screenshotDimensions': [640, 480], 'manifestValidation': validation,
        }
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        return report
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--three-root', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path, help='new directory for manifests, PNGs and logs')
    parser.add_argument('--timeout-ms', type=int, default=3000)
    args = parser.parse_args()
    report = run(args.three_root.expanduser().resolve(), args.out.expanduser().resolve(), args.timeout_ms)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
