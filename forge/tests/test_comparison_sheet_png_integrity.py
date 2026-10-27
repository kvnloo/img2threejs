"""Fail-closed PNG evidence checks for the review comparison sheet.

Small synthetic fixtures use stdlib only; no image libraries or browser needed.
"""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage4_review"))

from make_comparison_sheet import (  # noqa: E402
    InvalidPng, MAX_PNG_INPUT_BYTES, MAX_PNG_PIXELS, load_image, read_png,
)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(payload, zlib.crc32(kind)) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def png_bytes(
    *,
    width: int = 1,
    height: int = 1,
    color_type: int = 2,
    depth: int = 8,
    scanlines: bytes = b"\x00\x01\x02\x03",
    before_idat: bytes = b"",
) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, depth, color_type, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + before_idat
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


class ComparisonSheetPngIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "reference.png"

    def read(self, data: bytes):
        self.path.write_bytes(data)
        return read_png(self.path)

    def test_valid_png_decodes_identical_rgb(self):
        self.assertEqual(self.read(png_bytes()), (1, 1, [(1, 2, 3, 255)]))

    def test_valid_split_idat_and_ancillary_chunk_still_decode(self):
        data = png_bytes(before_idat=chunk(b"tEXt", b"Author\x00fixture"))
        pos = data.index(b"IDAT") - 4
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        payload = data[pos + 8:pos + 8 + size]
        split = data[:pos] + chunk(b"IDAT", payload[:2]) + chunk(b"IDAT", payload[2:]) + data[pos + 12 + size:]
        self.assertEqual(self.read(split), (1, 1, [(1, 2, 3, 255)]))

    def test_tampered_crc_is_not_accepted_as_real_image_evidence(self):
        image = bytearray(png_bytes())
        pos = image.index(b"IDAT") + 4
        image[pos] ^= 1
        with self.assertRaisesRegex(InvalidPng, "CRC mismatch"):
            self.read(bytes(image))

    def test_missing_iend_and_truncated_crc_rejected(self):
        full = png_bytes()
        for bad in (full[:-12], full[:-1]):
            with self.subTest(length=len(bad)):
                with self.assertRaises(InvalidPng):
                    self.read(bad)

    def test_trailing_bytes_after_iend_are_not_ignored(self):
        with self.assertRaisesRegex(InvalidPng, "IEND"):
            self.read(png_bytes() + b"extra")

    def test_short_and_excess_inflated_rows_are_rejected(self):
        for raw in (b"\x00\x01", b"\x00\x01\x02\x03\x04"):
            with self.subTest(length=len(raw)):
                with self.assertRaisesRegex(InvalidPng, "decoded length"):
                    self.read(png_bytes(scanlines=raw))

    def test_declared_pixel_count_fails_before_inflation(self):
        # 4000x3000 RGBA fits the scanline-byte bound yet would allocate
        # 12 million Python pixel tuples. The smaller pixel cap rejects it
        # even when the attacker supplies only a tiny compressed payload.
        self.assertGreater(4000 * 3000, MAX_PNG_PIXELS)
        with self.assertRaisesRegex(InvalidPng, "pixel count"):
            self.read(png_bytes(width=4000, height=3000))

    def test_oversized_sparse_png_is_refused_before_reading_into_memory(self):
        # Sparse file: large logical size with negligible disk usage.
        # An encoded-byte cap prevents reading hundreds of megabytes of
        # arbitrary ancillary chunk data before any parser bounds apply.
        with self.path.open("wb") as stream:
            stream.write(PNG_SIGNATURE)
            stream.truncate(MAX_PNG_INPUT_BYTES + 4096)
        with self.assertRaisesRegex(InvalidPng, "encoded-byte limit"):
            read_png(self.path)

    def test_non_png_still_uses_existing_format_dispatch(self):
        self.path.write_bytes(b"not-a-png")
        with self.assertRaisesRegex(ValueError, "not a PNG"):
            read_png(self.path)

    def test_decompression_limit_checked_before_allocating_pixels(self):
        with self.assertRaisesRegex(InvalidPng, "limit"):
            self.read(png_bytes(width=50000, height=50000))

    def test_bad_scanline_filter_is_not_accepted(self):
        with self.assertRaisesRegex(InvalidPng, "scanline filter"):
            self.read(png_bytes(scanlines=b"\x05\x01\x02\x03"))

    def test_corrupt_png_never_falls_back_to_sips(self):
        data = png_bytes()[:-12]
        self.path.write_bytes(data)
        with patch("make_comparison_sheet.shutil.which", return_value="/bin/sips"):
            with patch("make_comparison_sheet.subprocess.run", side_effect=AssertionError("converter must not run")):
                with self.assertRaises(InvalidPng):
                    load_image(self.path)

    def test_unsupported_valid_png_remains_convertible(self):
        with self.assertRaisesRegex(ValueError, "unsupported PNG"):
            self.read(png_bytes(depth=16))


if __name__ == "__main__":
    unittest.main()
