"""The pdf-ops skill teaches the four capabilities and their decided rules.

The skill is the only place an agent learns the package, so these tests
pin what a person reads: the front matter and the four headings the core
requires in order, every capability id, the tables-not-strings merge
shape, the 1-based page selection, the dpi bounds, and the sources table
with the licence of each PDF dependency.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "pdf-ops"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
SOURCES = (PACKAGE / "skill" / "references" / "sources.md").read_text(encoding="utf-8")
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
CAPABILITIES = ("pdf-ops.merge", "pdf-ops.split", "pdf-ops.compress", "pdf-ops.rasterize")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200


def _body() -> str:
    _first, _second, body = SKILL.split("---", 2)
    return body


def test_the_front_matter_parses_in_the_core_format() -> None:
    first, second, _rest = SKILL.split("---", 2)
    assert first == ""
    frontmatter = second.strip().splitlines()
    assert "name: pdf-ops" in frontmatter
    description = next(
        line.removeprefix("description:").strip()
        for line in frontmatter
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX


def test_the_four_headings_appear_in_order() -> None:
    positions = [_body().index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_skill_names_all_four_capabilities() -> None:
    body = _body()
    for capability in CAPABILITIES:
        assert capability in body


def test_the_skill_teaches_tables_not_strings_and_page_rules() -> None:
    body = _body()
    assert "[[inputs.pdf]]" in body
    assert "1-3,5" in body
    assert "150" in body
    assert "72" in body
    assert "300" in body


def test_the_sources_table_names_each_dependency_licence() -> None:
    assert "pikepdf" in SOURCES
    assert "MPL-2.0" in SOURCES
    assert "pypdfium2" in SOURCES
    assert "Apache-2.0" in SOURCES
    assert "pillow" in SOURCES.lower()
    assert "MIT-CMU" in SOURCES


def test_the_package_readme_mirrors_the_skill() -> None:
    readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
    for capability in CAPABILITIES:
        assert capability in readme
    assert "150" in readme
