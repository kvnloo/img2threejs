#!/usr/bin/env python3
"""Tests for Plan 1.3 §4.5 reference admission + the shared pHash (§3.1 signal).

Pure stdlib synthetic PNGs (RGB, 8-bit, non-interlaced — the format read_png parses
natively). No PIL/numpy.
"""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "stage1_intake"))
sys.path.insert(0, str(ROOT / "_shared"))

from check_reference_admission import check_admission, largest_component_fraction  # noqa: E402
from image_hash import hamming, phash_from_image, to_grayscale_downsampled  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_rgb_png(path: Path, w: int, h: int, pixel_fn) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(pixel_fn(x, y, w, h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = (
        PNG_SIGNATURE
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _centered_block(cx0, cy0, cx1, cy1, fg=(200, 30, 30), bg=(255, 255, 255)):
    def fn(x, y, w, h):
        return fg if (cx0 <= x < cx1 and cy0 <= y < cy1) else bg
    return fn


class ImageHashTest(unittest.TestCase):
    def _split_image(self, vertical: bool, size=64):
        px = []
        for y in range(size):
            for x in range(size):
                lo = (x if vertical else y) < size // 2
                v = 30 if lo else 220
                px.append((v, v, v, 255))
        return px

    def test_identical_hamming_zero(self):
        px = self._split_image(vertical=True)
        self.assertEqual(hamming(phash_from_image(64, 64, px), phash_from_image(64, 64, px)), 0)

    def test_brightness_shift_barely_changes_hash(self):
        px = self._split_image(vertical=True)
        bright = [(min(255, v + 20),) * 3 + (255,) for (v, _g, _b, _a) in px]
        bright = [(t[0], t[1], t[2], t[3]) for t in bright]
        self.assertLessEqual(hamming(phash_from_image(64, 64, px), phash_from_image(64, 64, bright)), 4)

    def test_small_image_scale_does_not_invent_black_hash_bands(self):
        # Before the fix, 16x16 fills only 256 of 1024 target cells and
        # differs from the same scene at 32x32 by 27/64 hash bits.
        reference = phash_from_image(32, 32, self._split_image(vertical=True, size=32))
        self.assertEqual(
            hamming(reference, phash_from_image(16, 16, self._split_image(vertical=True, size=16))),
            0,
        )
        for width, height in ((8, 16), (16, 64), (64, 16)):
            with self.subTest(width=width, height=height):
                pixels = [
                    (30, 30, 30, 255) if x < width // 2 else (220, 220, 220, 255)
                    for y in range(height) for x in range(width)
                ]
                self.assertLessEqual(hamming(reference, phash_from_image(width, height, pixels)), 2)

    def test_one_pixel_image_fills_every_output_cell(self):
        gray = to_grayscale_downsampled(1, 1, [(80, 160, 200, 255)], size=8)
        expected = 0.2126 * 80 + 0.7152 * 160 + 0.0722 * 200
        self.assertEqual(len(gray), 8)
        for row in gray:
            self.assertEqual(len(row), 8)
            for cell in row:
                self.assertAlmostEqual(cell, expected)

    def test_normal_resolution_hash_remains_byte_for_byte_stable(self):
        # Existing reference-admission hashes may be persisted between runs.
        # The fix must not silently invalidate high-resolution comparisons.
        self.assertEqual(
            phash_from_image(64, 64, self._split_image(vertical=True)),
            0xD500000000000000,
        )

    def test_truncated_small_pixel_payload_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "pixel payload"):
            phash_from_image(16, 16, [(255, 255, 255, 255)])

    def test_different_structure_differs_substantially(self):
        a = phash_from_image(64, 64, self._split_image(vertical=True))
        b = phash_from_image(64, 64, self._split_image(vertical=False))
        self.assertGreaterEqual(hamming(a, b), 8)


class ReferenceAdmissionTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_admits_coherent_centered_subject(self):
        p = self.dir / "good.png"
        write_rgb_png(p, 200, 200, _centered_block(50, 50, 150, 150))
        v = check_admission(p, viewpoint="side")
        self.assertTrue(v["admitted"], v["reasons"])
        self.assertGreater(v["provenance"]["largestComponentFraction"], 0.9)

    def test_rejects_no_isolable_subject(self):
        # all-background: build_foreground_mask's fallback treats every pixel as
        # foreground → coverage saturates → "no background to segment" rejection.
        p = self.dir / "blank.png"
        write_rgb_png(p, 200, 200, lambda x, y, w, h: (255, 255, 255))
        v = check_admission(p)
        self.assertFalse(v["admitted"])
        self.assertTrue(any("coverage" in r for r in v["reasons"]), v["reasons"])

    def test_rejects_tiny_resolution(self):
        p = self.dir / "tiny.png"
        write_rgb_png(p, 40, 40, _centered_block(10, 10, 30, 30))
        v = check_admission(p)
        self.assertFalse(v["admitted"])
        self.assertTrue(any("resolution floor" in r for r in v["reasons"]), v["reasons"])

    def test_rejects_fragmented_mask(self):
        # 16 separated 16×16 red squares on white → coverage ~0.10 (in band) but the
        # largest connected blob is a tiny fraction of foreground → coherence rejection.
        def fn(x, y, w, h):
            for gx in (10, 55, 100, 145):
                for gy in (10, 55, 100, 145):
                    if gx <= x < gx + 16 and gy <= y < gy + 16:
                        return (200, 30, 30)
            return (255, 255, 255)
        p = self.dir / "frag.png"
        write_rgb_png(p, 200, 200, fn)
        v = check_admission(p)
        self.assertFalse(v["admitted"])
        self.assertTrue(any("coherence" in r for r in v["reasons"]), v["reasons"])

    def test_rejects_duplicate(self):
        p = self.dir / "dup.png"
        write_rgb_png(p, 200, 200, _centered_block(50, 50, 150, 150))
        first = check_admission(p, viewpoint="front")
        self.assertTrue(first["admitted"], first["reasons"])
        again = check_admission(p, viewpoint="front", against_hashes=[first["provenance"]["pHash"]])
        self.assertFalse(again["admitted"])
        self.assertTrue(any("duplicate" in r for r in again["reasons"]), again["reasons"])

    def test_rejects_undecodable_cleanly(self):
        # a truncated/bogus file must be a clean rejection, never a crash/exit-2.
        p = self.dir / "bogus.png"
        p.write_bytes(PNG_SIGNATURE + b"\x00\x01\x02garbage")
        v = check_admission(p)
        self.assertFalse(v["admitted"])
        self.assertTrue(any("cannot decode" in r for r in v["reasons"]), v["reasons"])

    def test_largest_component_fraction_math(self):
        # one solid 4×4 blob in a 6×6 grid → fraction 1.0
        w = h = 6
        mask = [(1 <= i % w <= 4 and 1 <= i // w <= 4) for i in range(w * h)]
        self.assertAlmostEqual(largest_component_fraction(mask, w, h, grid=6), 1.0, places=3)
        # two separated single cells → largest fraction 0.5
        mask2 = [False] * (w * h)
        mask2[0] = True
        mask2[w * h - 1] = True
        self.assertAlmostEqual(largest_component_fraction(mask2, w, h, grid=6), 0.5, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
