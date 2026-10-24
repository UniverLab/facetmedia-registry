"""Tests for the kokoro package's pure text functions (no models needed).

``textnorm`` is the port of Grafics ``tools/voz.py``'s normalisation, so
these tests carry voz.py's own cases: accents fold (``vídeo`` → ``video``),
thousands dots drop (``1.200.000`` → ``1200000``), and Spanish numbers are
spelled so Whisper writing ``2026`` still matches ``dos mil veintiséis`` —
spelling happens only for ``es``, English keeps its digits. WER and the
word alignment are asserted on small examples with known answers: an
identical pair scores 0, one substituted word in three scores 1/3, and the
alignment marks ``ok``, ``sub``, ``del`` and ``ins`` with nulls on the
side that has no word.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kokoro_textnorm", ROOT / "packages" / "kokoro" / "textnorm.py"
)
assert SPEC is not None and SPEC.loader is not None
textnorm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(textnorm)


class TestSpell(unittest.TestCase):
    def test_year_two_thousand_twenty_six(self) -> None:
        self.assertEqual(textnorm.spell(2026), "dos mil veintiseis")

    def test_one_hundred_fifty(self) -> None:
        self.assertEqual(textnorm.spell(150), "ciento cincuenta")

    def test_units_and_tens(self) -> None:
        self.assertEqual(textnorm.spell(0), "cero")
        self.assertEqual(textnorm.spell(26), "veintiseis")
        self.assertEqual(textnorm.spell(45), "cuarenta y cinco")
        self.assertEqual(textnorm.spell(90), "noventa")

    def test_hundreds_and_thousands(self) -> None:
        self.assertEqual(textnorm.spell(100), "cien")
        self.assertEqual(textnorm.spell(101), "ciento uno")
        self.assertEqual(textnorm.spell(999), "novecientos noventa y nueve")
        self.assertEqual(textnorm.spell(1000), "mil")
        self.assertEqual(textnorm.spell(2000), "dos mil")
        self.assertEqual(
            textnorm.spell(999999), "novecientos noventa y nueve mil novecientos noventa y nueve"
        )


class TestWords(unittest.TestCase):
    def test_accents_fold(self) -> None:
        self.assertEqual(textnorm.words("Vídeo rápido", "en-us"), ["video", "rapido"])
        self.assertEqual(textnorm.words("¿Cómo estás?", "es"), ["como", "estas"])

    def test_thousands_dots_drop(self) -> None:
        self.assertEqual(textnorm.words("1.200.000", "es"), ["1200000"])
        self.assertEqual(textnorm.words("1.200.000", "en-us"), ["1200000"])

    def test_spanish_spells_numbers(self) -> None:
        self.assertEqual(textnorm.words("en 2026", "es"), ["en", "dos", "mil", "veintiseis"])

    def test_english_keeps_digits(self) -> None:
        self.assertEqual(textnorm.words("in 2026", "en-us"), ["in", "2026"])

    def test_million_stays_digits_even_in_spanish(self) -> None:
        # spell() covers 0..999999 only; a million stays a numeral.
        self.assertEqual(textnorm.words("1.000.000", "es"), ["1000000"])


class TestWer(unittest.TestCase):
    def test_identical_scores_zero(self) -> None:
        words = ["en", "este", "laboratorio"]
        self.assertEqual(textnorm.wer(words, list(words)), 0.0)

    def test_one_substitution_in_three(self) -> None:
        self.assertAlmostEqual(textnorm.wer(["a", "b", "c"], ["a", "x", "c"]), 1 / 3)

    def test_insertion_counts_toward_the_rate(self) -> None:
        self.assertAlmostEqual(textnorm.wer(["a", "b"], ["a", "x", "b"]), 1 / 2)

    def test_empty_reference_does_not_divide_by_zero(self) -> None:
        self.assertEqual(textnorm.wer([], ["a"]), 1.0)


class TestAlign(unittest.TestCase):
    def test_ok_and_sub(self) -> None:
        rows = textnorm.align(["hola", "mundo"], ["hola", "mundo"])
        self.assertEqual([row["op"] for row in rows], ["ok", "ok"])
        sub = textnorm.align(["the", "lab"], ["a", "lab"])
        self.assertEqual(sub[0], {"ref": "the", "hyp": "a", "op": "sub"})
        self.assertEqual(sub[1], {"ref": "lab", "hyp": "lab", "op": "ok"})

    def test_del_has_null_hyp(self) -> None:
        rows = textnorm.align(["old", "lab"], ["lab"])
        self.assertEqual(rows[0], {"ref": "old", "hyp": None, "op": "del"})
        self.assertEqual(rows[1], {"ref": "lab", "hyp": "lab", "op": "ok"})

    def test_ins_has_null_ref(self) -> None:
        rows = textnorm.align(["lab"], ["very", "lab"])
        self.assertEqual(rows[0], {"ref": None, "hyp": "very", "op": "ins"})
        self.assertEqual(rows[1], {"ref": "lab", "hyp": "lab", "op": "ok"})

    def test_alignment_length_matches_both_sides(self) -> None:
        rows = textnorm.align(["a", "b", "c"], ["a", "c"])
        refs = [row["ref"] for row in rows if row["ref"] is not None]
        hyps = [row["hyp"] for row in rows if row["hyp"] is not None]
        self.assertEqual(refs, ["a", "b", "c"])
        self.assertEqual(hyps, ["a", "c"])

    def test_ops_are_only_the_four(self) -> None:
        rows = textnorm.align(["one", "two", "three"], ["un", "too", "tree", "four"])
        self.assertLessEqual({row["op"] for row in rows}, {"ok", "sub", "del", "ins"})


if __name__ == "__main__":
    unittest.main()
