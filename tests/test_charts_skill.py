"""The charts skill teaches the one capability and its editorial rules.

The skill is the only place an agent learns the package, so these tests
pin what a person reads: the front matter and the four headings the core
requires in order, the capability id ``charts.render``, the chart and
format enums, the single-accent and source-citation rules, and the
references file behind them.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "charts"
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
    assert "name: charts" in frontmatter
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


def test_the_body_names_the_capability_and_the_chart_types() -> None:
    body = _body()
    assert "charts.render" in body
    for chart in ("bar", "barh", "line", "scatter"):
        assert chart in body, chart


def test_the_body_teaches_the_editorial_rules() -> None:
    body = _body()
    assert "accent" in body
    assert "source" in body
    assert "chartjunk" in body
    assert "preview" in body
    assert "doctor" in body


def test_the_references_file_lists_its_sources() -> None:
    references = PACKAGE / "skill" / "references" / "sources.md"
    assert references.is_file()
    text = references.read_text(encoding="utf-8")
    assert "matplotlib" in text
    assert "http" in text


def test_the_package_readme_describes_the_capability() -> None:
    readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
    assert "charts.render" in readme
    assert "bar" in readme and "scatter" in readme
