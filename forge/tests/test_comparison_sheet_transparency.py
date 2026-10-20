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


    def test_palette_length_must_be_complete_rgb_entries(self):
        for payload in (b"", b"ab", b"abcd", b"x" * 771):
            with self.subTest(length=len(payload)), self.assertRaisesRegex(InvalidPng, "PLTE"):
                self.decode(png_bytes(before_idat=chunk(b"PLTE", payload)))

    def test_duplicate_palette_metadata_is_rejected(self):
        part = chunk(b"PLTE", bytes((1, 2, 3)))
        with self.assertRaisesRegex(InvalidPng, "PLTE"):
            self.decode(png_bytes(before_idat=part + part))

    def test_two_palette_entries_still_decode_rgb(self):
        part = chunk(b"PLTE", bytes((1, 2, 3, 4, 5, 6)))
        self.assertEqual(self.decode(png_bytes(before_idat=part))[2], [(1, 2, 3, 255)])

    def test_rgba_may_carry_valid_optional_palette(self):
        part = chunk(b"PLTE", bytes((1, 2, 3)))
        source = png_bytes(color_type=6, scanlines=b"\\x00\\x01\\x02\\x03\\x04", before_idat=part)
        self.assertEqual(self.decode(source)[2], [(1, 2, 3, 4)])

    def test_indexed_transparency_requires_palette_first(self):
        part = chunk(b"tRNS", bytes((0,)))
        with self.assertRaisesRegex(InvalidPng, "preceding PLTE"):
            self.decode(png_bytes(color_type=3, scanlines=b"\\x00\\x00", before_idat=part))

    def test_indexed_transparency_must_fit_palette(self):
        palette = chunk(b"PLTE", bytes((1, 2, 3)))
        transparency = chunk(b"tRNS", bytes((0, 255)))
        with self.assertRaisesRegex(InvalidPng, "exceeds palette entries"):
            self.decode(png_bytes(
                color_type=3, scanlines=b"\\x00\\x00", before_idat=palette + transparency,
            ))

    def test_valid_indexed_metadata_reaches_unsupported_format_fallback(self):
        palette = chunk(b"PLTE", bytes((1, 2, 3)))
        transparency = chunk(b"tRNS", bytes((0,)))
        with self.assertRaisesRegex(ValueError, "unsupported PNG color type"):
            self.decode(png_bytes(
                color_type=3, scanlines=b"\\x00\\x00", before_idat=palette + transparency,
            ))


if __name__ == "__main__":
    unittest.main()
