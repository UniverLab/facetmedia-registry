"""Pure text functions for the kokoro package: normalisation, WER, alignment.

Stdlib only, so the tests import it without the package environment and no
model is ever needed. ``spell`` and ``words`` are ported from Grafics
``tools/voz.py`` (2026-10-19 lab), which handles Whisper writing ``2026``
where the text says "dos mil veintiséis": Spanish numbers are spelled into
words so the transcript and the text land on the same tokens.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

UNITS = (
    "cero",
    "uno",
    "dos",
    "tres",
    "cuatro",
    "cinco",
    "seis",
    "siete",
    "ocho",
    "nueve",
    "diez",
    "once",
    "doce",
    "trece",
    "catorce",
    "quince",
    "dieciseis",
    "diecisiete",
    "dieciocho",
    "diecinueve",
    "veinte",
    "veintiuno",
    "veintidos",
    "veintitres",
    "veinticuatro",
    "veinticinco",
    "veintiseis",
    "veintisiete",
    "veintiocho",
    "veintinueve",
)
TENS = ("treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa")
HUNDREDS = (
    "ciento",
    "doscientos",
    "trescientos",
    "cuatrocientos",
    "quinientos",
    "seiscientos",
    "setecientos",
    "ochocientos",
    "novecientos",
)
#: spell() steps from units to tens to hundreds to thousands at these bounds.
_TENS_AT = 30
_HUNDREDS_AT = 100
_THOUSANDS_AT = 1000
#: The one hundreds word Spanish has as a single form.
_CIENTO = 100
#: Digits glued to a decimal-looking dot are thousands separators: 1.200.000.
_THOUSANDS_DOT = re.compile(r"(?<=\d)\.(?=\d{3})")
_WORD = re.compile(r"\w+")
#: Numbers below this are spelled (Spanish only); Whisper writes them as digits.
_SPELL_BELOW = 10**6


def spell(number: int) -> str:
    """Spanish words for 0..999999, without accents (Whisper writes them flat)."""
    if number < _TENS_AT:
        return UNITS[number]
    if number < _HUNDREDS_AT:
        tens = TENS[number // 10 - 3]
        return tens if number % 10 == 0 else f"{tens} y {UNITS[number % 10]}"
    if number < _THOUSANDS_AT:
        if number == _CIENTO:
            return "cien"
        head = HUNDREDS[number // 100 - 1]
        return head if number % 100 == 0 else f"{head} {spell(number % 100)}"
    thousands = "mil" if number // 1000 == 1 else f"{spell(number // 1000)} mil"
    return thousands if number % 1000 == 0 else f"{thousands} {spell(number % 1000)}"


def words(text: str, language: str) -> list[str]:
    """Normalise ``text`` into comparable tokens for ``language``.

    Lowercase, strip accents (NFKD, combining marks dropped), drop the dots
    of thousands, and — only for Spanish — spell numbers below 10**6 into
    words, because the transcript writes "2026" where the text says the year
    in words. English keeps its digits as digits.
    """
    normalised = unicodedata.normalize("NFKD", text.lower())
    normalised = "".join(char for char in normalised if not unicodedata.combining(char))
    normalised = _THOUSANDS_DOT.sub("", normalised)
    if language == "es":
        normalised = re.sub(r"\d+", _spell_spanish, normalised)
    return _WORD.findall(normalised)


def _spell_spanish(match: re.Match[str]) -> str:
    value = int(match.group())
    return spell(value) if value < _SPELL_BELOW else match.group()


def wer(reference: Sequence[str], hypothesis: Sequence[str]) -> float:
    """Word error rate: word-level Levenshtein distance over the reference."""
    row = list(range(len(hypothesis) + 1))
    for i, ref_word in enumerate(reference, 1):
        previous, row[0] = row[0], i
        for j, hyp_word in enumerate(hypothesis, 1):
            substitution = previous + (ref_word != hyp_word)
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, substitution)
    return row[-1] / max(len(reference), 1)


def align(reference: Sequence[str], hypothesis: Sequence[str]) -> list[dict[str, str | None]]:
    """Word alignment of the two token sequences as ``{ref, hyp, op}`` rows.

    ``op`` is ``ok`` or ``sub`` on the diagonal, ``del`` consumes a reference
    word (``hyp`` null) and ``ins`` consumes a transcript word (``ref`` null).
    """
    dist = _distance(reference, hypothesis)
    rows: list[dict[str, str | None]] = []
    i, j = len(reference), len(hypothesis)
    while i > 0 or j > 0:
        op = _step(reference, hypothesis, dist, i, j)
        if op == "ins":
            rows.append({"ref": None, "hyp": hypothesis[j - 1], "op": "ins"})
            j -= 1
        elif op == "del":
            rows.append({"ref": reference[i - 1], "hyp": None, "op": "del"})
            i -= 1
        else:
            same = reference[i - 1] == hypothesis[j - 1]
            rows.append(
                {"ref": reference[i - 1], "hyp": hypothesis[j - 1], "op": "ok" if same else "sub"}
            )
            i -= 1
            j -= 1
    rows.reverse()
    return rows


def _distance(reference: Sequence[str], hypothesis: Sequence[str]) -> list[list[int]]:
    """The full Levenshtein matrix, rows over ``reference``, cols over ``hyp``."""
    dist = [[0] * (len(hypothesis) + 1) for _ in range(len(reference) + 1)]
    for i in range(len(reference) + 1):
        dist[i][0] = i
    for j in range(len(hypothesis) + 1):
        dist[0][j] = j
    for i in range(1, len(reference) + 1):
        for j in range(1, len(hypothesis) + 1):
            cost = 0 if reference[i - 1] == hypothesis[j - 1] else 1
            dist[i][j] = min(dist[i - 1][j] + 1, dist[i][j - 1] + 1, dist[i - 1][j - 1] + cost)
    return dist


def _step(
    reference: Sequence[str], hypothesis: Sequence[str], dist: list[list[int]], i: int, j: int
) -> str:
    """The backtrace move at ``(i, j)``: diagonal first, then delete, then insert."""
    if i > 0 and j > 0:
        cost = 0 if reference[i - 1] == hypothesis[j - 1] else 1
        if dist[i][j] == dist[i - 1][j - 1] + cost:
            return "diag"
    if i > 0 and dist[i][j] == dist[i - 1][j] + 1:
        return "del"
    return "ins"
