"""Tests for the kokoro package's short espeak-ng data path (stdlib only).

espeak-ng cannot read its data from a path longer than its fixed buffer and
does not follow a symlink, so the runner hands it a short copy: a short path
comes back unchanged, a long one becomes a real directory in the given base
holding the same files, a second call reuses it, and a copy missing its
marker file is rebuilt.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kokoro_espeakpath", ROOT / "packages" / "kokoro" / "espeakpath.py"
)
assert SPEC is not None and SPEC.loader is not None
espeakpath = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(espeakpath)


class TestShortDataPath(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.base = self.tmp / "base"
        self.base.mkdir()
        self.data = self.tmp / ("d" * 40) / ("e" * 40) / ("f" * 40) / "espeak-ng-data"
        self.data.mkdir(parents=True)
        (self.data / "phontab").write_bytes(b"x")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_short_path_is_returned_as_is(self) -> None:
        short = "/tmp/espeak-ng-data"
        self.assertEqual(espeakpath.short_data_path(short, self.base), short)

    def test_long_path_becomes_a_short_copy_of_the_same_data(self) -> None:
        self.assertGreater(len(str(self.data)), espeakpath.MAX_DATA_PATH)
        short = Path(espeakpath.short_data_path(str(self.data), self.base))
        self.assertFalse(short.is_symlink())
        self.assertTrue(short.is_dir())
        self.assertEqual(short.parent, self.base)
        self.assertEqual((short / "phontab").read_bytes(), b"x")
        self.assertLessEqual(len(str(short)), espeakpath.MAX_DATA_PATH)

    def test_second_call_reuses_the_copy(self) -> None:
        first = Path(espeakpath.short_data_path(str(self.data), self.base))
        (first / "reused").write_bytes(b"")
        second = Path(espeakpath.short_data_path(str(self.data), self.base))
        self.assertEqual(first, second)
        self.assertTrue((second / "reused").exists())

    def test_copy_without_marker_is_rebuilt(self) -> None:
        first = Path(espeakpath.short_data_path(str(self.data), self.base))
        (first / "phontab").unlink()
        again = Path(espeakpath.short_data_path(str(self.data), self.base))
        self.assertEqual(again, first)
        self.assertTrue((again / "phontab").is_file())
        self.assertEqual([p.name for p in self.base.iterdir()], [first.name])

    def test_limit_is_configurable(self) -> None:
        short = espeakpath.short_data_path(str(self.data), self.base, limit=10)
        self.assertNotEqual(short, str(self.data))


if __name__ == "__main__":
    unittest.main()
