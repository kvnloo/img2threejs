"""PNG transparency-key and chunk-order regressions for visual-review evidence."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from forge.tests.test_comparison_sheet_png_integrity import chunk, png_bytes
from forge.stage4_review.make_comparison_sheet import InvalidPng, read_png


class PngTransparencyEvidenceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "source.png"

    def decode(self, source):
        self.path.write_bytes(source)
        return read_png(self.path)

    def test_matching_rgb_transparency_key_preserves_alpha(self):
        marker = chunk(b"tRNS", struct.pack(">HHH", 1, 2, 3))
        width, height, pixels = self.decode(png_bytes(before_idat=marker))
        self.assertEqual((width, height, pixels), (1, 1, [(1, 2, 3, 0)]))

    def test_nonmatching_rgb_key_does_not_fabricate_alpha(self):
        marker = chunk(b"tRNS", struct.pack(">HHH", 4, 5, 6))
        self.assertEqual(self.decode(png_bytes(before_idat=marker))[2], [(1, 2, 3, 255)])

    def test_matching_grayscale_key_preserves_alpha(self):
        marker = chunk(b"tRNS", struct.pack(">H", 9))
        image = png_bytes(color_type=0, scanlines=b"\x00\x09", before_idat=marker)
        self.assertEqual(self.decode(image)[2], [(9, 9, 9, 0)])

    def test_grayscale_without_key_remains_opaque(self):
        image = png_bytes(color_type=0, scanlines=b"\x00\x09")
        self.assertEqual(self.decode(image)[2], [(9, 9, 9, 255)])

    def test_transparency_key_after_idat_is_refused(self):
        original = png_bytes()
        late = original[:-12] + chunk(b"tRNS", struct.pack(">HHH", 1, 2, 3)) + original[-12:]
        with self.assertRaisesRegex(InvalidPng, "tRNS"):
            self.decode(late)

    def test_duplicate_transparency_key_is_refused(self):
        marker = chunk(b"tRNS", struct.pack(">HHH", 1, 2, 3))
        with self.assertRaisesRegex(InvalidPng, "tRNS"):
            self.decode(png_bytes(before_idat=marker + marker))

    def test_invalid_rgba_extra_transparency_key_is_refused(self):
        marker = chunk(b"tRNS", struct.pack(">H", 1))
        with self.assertRaisesRegex(InvalidPng, "tRNS"):
            self.decode(png_bytes(color_type=6, scanlines=b"\x00\x01\x02\x03\x04", before_idat=marker))

    def test_palette_after_idat_is_refused(self):
        original = png_bytes()
        late = original[:-12] + chunk(b"PLTE", b"\x01\x02\x03") + original[-12:]
        with self.assertRaisesRegex(InvalidPng, "PLTE"):
            self.decode(late)

    def test_valid_rgb_palette_metadata_remains_compatible(self):
        marker = chunk(b"PLTE", b"\x01\x02\x03")
        self.assertEqual(self.decode(png_bytes(before_idat=marker))[2], [(1, 2, 3, 255)])

    def test_grayscale_palette_metadata_is_rejected(self):
        marker = chunk(b"PLTE", b"\x01\x02\x03")
        with self.assertRaisesRegex(InvalidPng, "PLTE"):
            self.decode(png_bytes(color_type=0, scanlines=b"\x00\x09", before_idat=marker))

    def test_high_bit_rgb_transparency_key_is_refused(self):
        marker = chunk(b"tRNS", struct.pack(">HHH", 257, 2, 3))
        with self.assertRaisesRegex(InvalidPng, "exceeds sample depth"):
            self.decode(png_bytes(before_idat=marker))


if __name__ == "__main__":
    unittest.main()
