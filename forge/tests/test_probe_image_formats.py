#!/usr/bin/env python3
"""Regression tests for lossless WebP and endian-sensitive TIFF header probing.

Pure stdlib fixtures: the WebP bytes were encoded from a 1024x513 solid RGBA
image using Pillow in lossless mode, but Pillow is not used by the test suite.
"""

from __future__ import annotations

import base64
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "forge" / "stage1_intake"))
from probe_image import detect_size, probe, tiff_size, webp_size  # noqa: E402


LOSSLESS_WEBP = base64.b64decode(
    "UklGRjoAAABXRUJQVlA4TC4AAAAv/wOAAAfQy64Uqv8BIUHi//FWIvqf8Z///Oc///nPf/7zn//85z//+c9//u8A"
)


def _tiff_ifd(endian: str, width: int, height: int, value_type: int = 3) -> bytes:
    """Two inline width/height tags: SHORT or LONG, in either TIFF byte order."""
    header = (b"II*\x00" if endian == "<" else b"MM\x00*") + struct.pack(
        f"{endian}I", 8
    )
    def entry(tag: int, value: int) -> bytes:
        raw = (struct.pack(f"{endian}H", value) + b"\x00\x00"
               if value_type == 3 else struct.pack(f"{endian}I", value))
        return struct.pack(f"{endian}HHI", tag, value_type, 1) + raw
    return (
        header + struct.pack(f"{endian}H", 2)
        + entry(256, width) + entry(257, height)
        + struct.pack(f"{endian}I", 0)
    )


class ProbeImageFormatsTest(unittest.TestCase):
    def test_lossless_webp_header_and_technical_probe(self):
        self.assertEqual(LOSSLESS_WEBP[12:16], b"VP8L")
        self.assertEqual(webp_size(LOSSLESS_WEBP), (1024, 513))
        self.assertEqual(detect_size(LOSSLESS_WEBP), (1024, 513))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.webp"
            path.write_bytes(LOSSLESS_WEBP)
            result = probe(path)
            self.assertEqual((result["width"], result["height"]), (1024, 513))
            self.assertEqual(result["technicalSuitability"], "pass")
            self.assertEqual(result["warnings"], [])

    def test_bad_lossless_webp_headers_are_not_assumed_to_have_dimensions(self):
        self.assertIsNone(webp_size(LOSSLESS_WEBP[:24]))
        bad_signature = bytearray(LOSSLESS_WEBP)
        bad_signature[20] = 0
        self.assertIsNone(webp_size(bytes(bad_signature)))
        short_chunk = bytearray(LOSSLESS_WEBP)
        short_chunk[16:20] = (4).to_bytes(4, "little")
        self.assertIsNone(webp_size(bytes(short_chunk)))
        bad_version = bytearray(LOSSLESS_WEBP)
        packed = int.from_bytes(bad_version[21:25], "little") | (1 << 29)
        bad_version[21:25] = packed.to_bytes(4, "little")
        self.assertIsNone(webp_size(bytes(bad_version)))

    def test_inline_short_tiff_dimensions_in_both_byte_orders(self):
        for endian in ("<", ">"):
            with self.subTest(endian=endian):
                data = _tiff_ifd(endian, 1024, 513)
                self.assertEqual(tiff_size(data), (1024, 513))
                self.assertEqual(detect_size(data), (1024, 513))

    def test_long_tiff_dimensions_remain_supported(self):
        for endian in ("<", ">"):
            with self.subTest(endian=endian):
                data = _tiff_ifd(endian, 1024, 513, value_type=4)
                self.assertEqual(tiff_size(data), (1024, 513))


if __name__ == "__main__":
    unittest.main()
