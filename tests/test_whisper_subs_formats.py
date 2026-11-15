"""Tests for the whisper-subs package's pure sidecar and writers.

``formats`` turns a whisper JSON sidecar into the validated subtitle file.
The cases pin what a reviewer reads: a timestamp renders through both
separators (comma for SRT, dot for VTT), the SRT cues are numbered and blank
line separated while the VTT opens on ``WEBVTT`` and stays unnumbered, an
overlap or a regression is rejected naming its 1-based cue, cue boundaries
that touch are allowed, and ``parse_timings`` reads both renderings back to
the same timings. Stdlib only, so no model is ever needed.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "whisper_subs_formats", ROOT / "packages" / "whisper-subs" / "formats.py"
)
assert SPEC is not None and SPEC.loader is not None
formats = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = formats
SPEC.loader.exec_module(formats)

#: Two touching cues: cue 2 starts exactly when cue 1 ends.
CUES = [
    formats.Cue(start_s=0.0, end_s=1.5, text="Hola."),
    formats.Cue(start_s=1.5, end_s=3.25, text="Mundo."),
]

EXPECTED_SRT = (
    "1\n00:00:00,000 --> 00:00:01,500\nHola.\n\n2\n00:00:01,500 --> 00:00:03,250\nMundo.\n"
)
EXPECTED_VTT = (
    "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHola.\n\n00:00:01.500 --> 00:00:03.250\nMundo.\n"
)
EXPECTED_TIMINGS = [(0, 1500), (1500, 3250)]


def _cues(segments: list[dict[str, Any]]) -> list[formats.Cue]:
    """Segments as cues read the way ``read_sidecar`` reads its list."""
    return [formats._cue(segment, index) for index, segment in enumerate(segments, start=1)]


class TestTimestamp(unittest.TestCase):
    def test_one_and_a_half_through_both_separators(self) -> None:
        self.assertEqual(formats.format_timestamp(1.5, sep=","), "00:00:01,500")
        self.assertEqual(formats.format_timestamp(1.5, sep="."), "00:00:01.500")

    def test_zero_and_hours(self) -> None:
        self.assertEqual(formats.format_timestamp(0, sep=","), "00:00:00,000")
        self.assertEqual(formats.format_timestamp(3661.5, sep=","), "01:01:01,500")

    def test_negative_clamps_to_zero(self) -> None:
        self.assertEqual(formats.format_timestamp(-0.4, sep=","), "00:00:00,000")


class TestRead(unittest.TestCase):
    def test_validation_errors_name_the_cue(self) -> None:
        cases: list[tuple[dict[str, Any], str]] = [
            ({"start_s": 2.0, "end_s": 1.0, "text": "hola"}, "cue 2: start_s 2.0"),
            ({"start_s": 1.0, "end_s": 1.0, "text": "hola"}, "cue 2: start_s 1.0"),
            ({"start_s": True, "end_s": 2.0, "text": "hola"}, "cue 2: start_s must be a number"),
            ({"start_s": "1", "end_s": 2.0, "text": "hola"}, "cue 2: start_s must be a number"),
        ]
        for segment, message in cases:
            with self.assertRaisesRegex(ValueError, message):
                _cues([{"start_s": 0.0, "end_s": 1.0, "text": "ok"}, segment])

    def test_non_object_segment_names_the_cue(self) -> None:
        with self.assertRaisesRegex(ValueError, "cue 2: not a JSON object"):
            _cues([{"start_s": 0.0, "end_s": 1.0, "text": "ok"}, "hola"])

    def test_text_is_stripped_and_defaults_to_empty(self) -> None:
        cues = _cues(
            [
                {"start_s": 0.0, "end_s": 1.0, "text": " hola "},
                {"start_s": 1.0, "end_s": 2.0},
            ]
        )
        self.assertEqual([cue.text for cue in cues], ["hola", ""])


class TestValidate(unittest.TestCase):
    def test_touching_boundaries_pass(self) -> None:
        formats.validate_cues(CUES)

    def test_same_start_twice_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cue 2: starts before cue 1 ends"):
            formats.validate_cues(
                [
                    formats.Cue(0.0, 2.0, "hola"),
                    formats.Cue(0.0, 3.0, "mundo"),
                ]
            )

    def test_overlap_names_the_second_cue(self) -> None:
        with self.assertRaisesRegex(ValueError, "cue 2: starts before cue 1 ends"):
            formats.validate_cues(
                [
                    formats.Cue(0.0, 1.5, "hola"),
                    formats.Cue(1.0, 3.0, "mundo"),
                ]
            )

    def test_regression_naming_the_third_cue(self) -> None:
        with self.assertRaisesRegex(ValueError, "cue 3: starts before cue 2 ends"):
            formats.validate_cues(
                [
                    formats.Cue(0.0, 1.0, "hola"),
                    formats.Cue(1.0, 2.0, "mundo"),
                    formats.Cue(1.5, 3.0, "loco"),
                ]
            )


class TestWriters(unittest.TestCase):
    def test_srt_is_numbered_with_comma_times(self) -> None:
        self.assertEqual(formats.to_srt(CUES), EXPECTED_SRT)

    def test_vtt_opens_on_the_header_with_dot_times(self) -> None:
        self.assertEqual(formats.to_vtt(CUES), EXPECTED_VTT)


class TestParse(unittest.TestCase):
    def test_both_renderings_parse_to_the_same_timings(self) -> None:
        self.assertEqual(formats.parse_timings(EXPECTED_SRT), EXPECTED_TIMINGS)
        self.assertEqual(formats.parse_timings(EXPECTED_VTT), EXPECTED_TIMINGS)

    def test_missing_arrow_line_parses_to_nothing(self) -> None:
        self.assertEqual(formats.parse_timings("no timestamps here"), [])


if __name__ == "__main__":
    unittest.main()
