"""The whisper package carries a byte-identical copy of kokoro's ``textnorm``.

Packages run in separate environments and cannot import each other, so the
normalisation and the WER are copied instead of shared. This test is what
keeps the two copies from drifting: the whisper runner's word error rate must
match the one kokoro's verify uses, down to the byte.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KOKORO = ROOT / "packages" / "kokoro" / "textnorm.py"
WHISPER = ROOT / "packages" / "whisper" / "textnorm.py"


class TestTextnormCopies(unittest.TestCase):
    def test_whisper_copy_is_byte_identical(self) -> None:
        self.assertTrue(KOKORO.is_file(), f"{KOKORO} is missing")
        self.assertTrue(WHISPER.is_file(), f"{WHISPER} is missing")
        self.assertEqual(WHISPER.read_bytes(), KOKORO.read_bytes())


if __name__ == "__main__":
    unittest.main()
