"""The vtracer skill teaches when to trace, the piece shape and the verdicts.

The skill is the only place an agent learns the package, so these tests
pin what a person reads: the front matter and the four headings the core
requires in order, the capability id ``vtracer.trace``, the trace-vs-redraw
rule and the photographic-source pitfall, and the sources file behind it.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "vtracer"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200


def _body() -> str:
    _first, _second, body = SKILL.split("---", 2)
    return body


def test_the_front_matter_parses_in_the_core_format() -> None:
    first, second, _rest = SKILL.split("---", 2)
    assert first == ""
    frontmatter = second.strip().splitlines()
    assert "name: vtracer" in frontmatter
    description = next(
        line.removeprefix("description:").strip()
        for line in frontmatter
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX


def test_the_four_headings_appear_in_order() -> None:
    body = _body()
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_body_names_the_capability_and_the_options() -> None:
    body = _body()
    assert "vtracer.trace" in body
    for token in ("colormode", "filter-speckle", "color-precision", "binary", "polygon"):
        assert token in body, token


def test_the_skill_teaches_trace_vs_redraw() -> None:
    body = _body().lower()
    assert "redraw" in body
    assert "trace" in body


def test_the_skill_warns_about_photographic_sources() -> None:
    body = _body().lower()
    assert "photo" in body
    assert "rembg" in body or "redraw" in body


def test_the_sources_file_exists_and_names_vtracer() -> None:
    sources = PACKAGE / "skill" / "references" / "sources.md"
    assert sources.is_file()
    text = sources.read_text(encoding="utf-8")
    assert "VTracer" in text or "vtracer" in text
    assert "MIT" in text
