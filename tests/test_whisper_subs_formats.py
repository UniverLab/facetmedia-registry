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


def _worded(start_s: float, end_s: float, spans: list[tuple[str, float, float]]) -> formats.Cue:
    """One word-timed cue from ``(word, start, end)`` spans."""
    words = [formats.Word(word, start, end) for word, start, end in spans]
    text = " ".join(word for word, _start, _end in spans)
    return formats.Cue(start_s, end_s, text, tuple(words))


def _even_words(
    count: int, start_s: float, step_s: float, length_s: float
) -> list[tuple[str, float, float]]:
    """``count`` evenly spaced single-word spans, the uniform-speech case."""
    return [
        (f"w{index}", start_s + index * step_s, start_s + index * step_s + length_s)
        for index in range(count)
    ]


class TestWrap(unittest.TestCase):
    def test_short_text_stays_one_line(self) -> None:
        self.assertEqual(formats._wrap("Hola mundo.", 42), ["Hola mundo."])

    def test_long_text_wraps_at_word_boundaries(self) -> None:
        text = "In this laboratory we test a locally generated English voice."
        lines = formats._wrap(text, 42)
        self.assertTrue(len(lines) > 1)
        for line in lines:
            self.assertLessEqual(len(line), 42)
        self.assertEqual(" ".join(lines), text)

    def test_an_overlong_word_stays_whole(self) -> None:
        word = "x" * 60
        self.assertEqual(formats._wrap(f"{word} yes", 42), [word, "yes"])

    def test_empty_text_wraps_to_one_empty_line(self) -> None:
        self.assertEqual(formats._wrap("", 42), [""])


class TestShapeSplit(unittest.TestCase):
    def test_a_long_uniform_segment_splits_into_fitting_pieces(self) -> None:
        cue = _worded(0.0, 10.0, _even_words(20, 0.0, 0.5, 0.4))
        shaped = formats.shape_cues([cue], formats.Limits())
        self.assertEqual(len(shaped), 2)
        for piece in shaped:
            self.assertLessEqual(piece.end_s - piece.start_s, 7.0)
            for line in piece.text.split("\n"):
                self.assertLessEqual(len(line), 42)
            self.assertLessEqual(len(piece.text.split("\n")), 2)
        self.assertEqual(shaped[0].start_s, 0.0)
        self.assertEqual(shaped[-1].end_s, 10.0)
        self.assertLessEqual(shaped[1].start_s - shaped[0].end_s, 0.25 + 1e-9)
        kept = " ".join(line for piece in shaped for line in piece.text.split("\n"))
        self.assertEqual(kept.split(), cue.text.split())

    def test_a_split_cuts_at_the_widest_silence(self) -> None:
        spans = [
            ("a", 0.0, 0.4),
            ("b", 0.5, 0.9),
            ("c", 1.0, 1.4),
            ("d", 1.5, 1.9),
            ("e", 5.0, 5.4),
            ("f", 5.5, 5.9),
            ("g", 6.0, 6.4),
            ("h", 6.5, 6.9),
        ]
        shaped = formats.shape_cues([_worded(0.0, 9.0, spans)], formats.Limits())
        self.assertEqual(len(shaped), 2)
        self.assertEqual([piece.text for piece in shaped], ["a b c d", "e f g h"])
        self.assertAlmostEqual(shaped[0].end_s, 1.9)
        self.assertAlmostEqual(shaped[1].start_s, 5.0)

    def test_a_wordless_segment_stays_one_cue_and_wraps(self) -> None:
        text = "In this laboratory we test a locally generated English voice today."
        shaped = formats.shape_cues([formats.Cue(0.0, 10.0, text)], formats.Limits())
        self.assertEqual(len(shaped), 1)
        for line in shaped[0].text.split("\n"):
            self.assertLessEqual(len(line), 42)

    def test_a_single_forced_word_is_kept_not_dropped(self) -> None:
        cue = _worded(0.0, 1.0, [("x" * 60, 0.0, 1.0)])
        shaped = formats.shape_cues([cue], formats.Limits())
        self.assertEqual(len(shaped), 1)
        self.assertEqual(shaped[0].text, "x" * 60)


class TestShapeMerge(unittest.TestCase):
    def test_contiguous_shorts_merge_into_one_cue(self) -> None:
        cues = [formats.Cue(0.0, 0.5, "Hola."), formats.Cue(0.5, 1.5, "Mundo.")]
        shaped = formats.shape_cues(cues, formats.Limits())
        self.assertEqual(len(shaped), 1)
        self.assertEqual((shaped[0].start_s, shaped[0].end_s), (0.0, 1.5))
        self.assertEqual(shaped[0].text, "Hola. Mundo.")

    def test_a_silence_gap_blocks_the_merge(self) -> None:
        cues = [formats.Cue(0.0, 0.5, "Hola."), formats.Cue(2.5, 3.5, "Mundo.")]
        shaped = formats.shape_cues(cues, formats.Limits())
        self.assertEqual(len(shaped), 2)
        self.assertEqual([cue.text for cue in shaped], ["Hola.", "Mundo."])

    def test_an_overlap_never_merges(self) -> None:
        cues = [formats.Cue(0.0, 0.5, "Hola."), formats.Cue(0.4, 1.5, "Mundo.")]
        shaped = formats.shape_cues(cues, formats.Limits())
        self.assertEqual(len(shaped), 2)

    def test_a_merge_that_breaks_the_ceiling_is_refused(self) -> None:
        cues = [formats.Cue(0.0, 0.5, "Hola."), formats.Cue(0.5, 8.0, "Mundo.")]
        shaped = formats.shape_cues(cues, formats.Limits())
        self.assertEqual(len(shaped), 2)


class TestParseBlocks(unittest.TestCase):
    def test_blocks_carry_text_lines_and_the_longest_line(self) -> None:
        blocks = formats.parse_blocks(EXPECTED_SRT)
        self.assertEqual([(block.start_ms, block.end_ms) for block in blocks], EXPECTED_TIMINGS)
        self.assertEqual([block.lines for block in blocks], [("Hola.",), ("Mundo.",)])
        self.assertEqual([block.chars for block in blocks], [5, 6])

    def test_a_two_line_cue_reports_both(self) -> None:
        text = "1\n00:00:00,000 --> 00:00:01,500\nHola mundo cruel.\nAdios.\n"
        (block,) = formats.parse_blocks(text)
        self.assertEqual(block.lines, ("Hola mundo cruel.", "Adios."))
        self.assertEqual(block.chars, len("Hola mundo cruel."))
        self.assertEqual((block.start_ms, block.end_ms), (0, 1500))

    def test_missing_arrow_line_parses_to_nothing(self) -> None:
        self.assertEqual(formats.parse_blocks("no timestamps here"), [])


if __name__ == "__main__":
    unittest.main()
