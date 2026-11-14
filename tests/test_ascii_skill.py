"""The ascii skill teaches sampling, judging, and reproducibility.

The skill is the only place an agent learns the package, so these tests pin
what a person reads: the front matter, the four headings the core requires
in order, and the sources table the guidance draws on. The topic pins fail
if the sampling and judging paragraphs are removed.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "ascii"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")


def _body() -> str:
    _first, _second, body = SKILL.split("---", 2)
    return body


def test_the_front_matter_names_the_skill() -> None:
    first, second, _rest = SKILL.split("---", 2)
    assert first == ""
    assert "name: ascii" in second.splitlines()


def test_the_four_headings_appear_in_order() -> None:
    body = _body()
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_skill_cites_its_sources_reference() -> None:
    """The skill links its sources table, and the file ships beside it."""
    sources = PACKAGE / "skill" / "references" / "sources.md"
    assert sources.is_file()
    assert sources.stat().st_size > 0
    assert "references/sources.md" in SKILL


def test_the_skill_teaches_sampling_and_judging() -> None:
    """The sampling guidance: decide first, sample, judge monospace, pin."""
    body = _body()
    flat = " ".join(body.lower().split())
    assert "sample before choosing" in flat
    assert "intended look first" in flat
    assert "fonts sheet is the sampler" in flat
    assert "monospaced" in flat
    assert "pin `width` and `mode`" in flat
    assert "bug signal" in flat
