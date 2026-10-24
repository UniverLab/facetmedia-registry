"""The ffmpeg package carries a byte-identical copy of kokoro's ``audiopreview``.

Packages run in separate environments and cannot import each other, so the
waveform, momentary loudness, silence and clipping measurement is copied
instead of shared. This test is what keeps the two copies from drifting:
both runners must measure an audio preview the same way, down to the byte.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KOKORO = ROOT / "packages" / "kokoro" / "audiopreview.py"
FFMPEG = ROOT / "packages" / "ffmpeg" / "audiopreview.py"


class TestAudiopreviewCopies(unittest.TestCase):
    def test_ffmpeg_copy_is_byte_identical(self) -> None:
        self.assertTrue(KOKORO.is_file(), f"{KOKORO} is missing")
        self.assertTrue(FFMPEG.is_file(), f"{FFMPEG} is missing")
        self.assertEqual(FFMPEG.read_bytes(), KOKORO.read_bytes())


if __name__ == "__main__":
    unittest.main()
