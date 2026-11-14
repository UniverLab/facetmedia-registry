"""The mermaid skill: front matter, the four headings, the capability, and the port.

The skill teaches the lab's diagram knowledge: the header traps the runner
enforces, the two cited reference files, the approved examples, and the stable
SVG ids that HyperFrames animates. ``name`` and ``description`` live in the
front matter, then ``## When to use``, ``## Pieces``, ``## Judging the result``
and ``## Pitfalls`` appear in order, with the capability id named in the body.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "mermaid"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
CITED_REFERENCES = {"headers", "architecture"}
EXAMPLE_FILES = (
    "cycle.mmd",
    "cycle.svg",
    "cycle.png",
    "architecture.mmd",
    "architecture.svg",
    "architecture.png",
    "cycle-hand.png",
)
STABLE_ID_TOKENS = (
    "my-svg-flowchart-",
    "my-svg-L_",
    "data-id",
    "strokeDashoffset",
    "local('Ubuntu')",
)


def _body() -> str:
    _first, _second, body = SKILL.split("---", 2)
    return body


def test_the_front_matter_parses_in_the_core_format() -> None:
    first, second, _rest = SKILL.split("---", 2)
    assert first == ""
    frontmatter = second.strip().splitlines()
    assert "name: mermaid" in frontmatter
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


def test_the_body_names_the_capability() -> None:
    assert "mermaid.diagram" in _body()


def test_the_skill_teaches_the_header_traps() -> None:
    """The traps the runner enforces are the ones the skill warns about."""
    body = _body()
    for token in ("fontFamily", "Ubuntu Sans", "FACET_BROWSER", "PUPPETEER_SKIP_DOWNLOAD"):
        assert token in body, token


def test_every_cited_reference_exists_and_is_non_empty() -> None:
    """The skill cites exactly the references/ files that ship, and they carry text."""
    cited = set(re.findall(r"references/([a-z0-9][a-z0-9-]*)\.md", _body()))
    assert cited == CITED_REFERENCES
    references_dir = PACKAGE / "skill" / "references"
    for name in cited:
        reference = references_dir / f"{name}.md"
        assert reference.is_file(), reference
        assert reference.stat().st_size > 0, reference


def test_the_skill_pins_the_stable_ids() -> None:
    """The HyperFrames-animation tokens are named, so an agent can target them."""
    body = _body()
    for token in STABLE_ID_TOKENS:
        assert token in body, token


def test_the_approved_examples_ship() -> None:
    """The skill cites the two approved pieces and all their files are present."""
    body = _body()
    assert "examples/cycle.mmd" in body
    assert "examples/architecture.mmd" in body
    examples_dir = PACKAGE / "examples"
    for name in EXAMPLE_FILES:
        example = examples_dir / name
        assert example.is_file(), example
        assert example.stat().st_size > 0, example
