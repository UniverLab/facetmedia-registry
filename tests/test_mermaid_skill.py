"""The mermaid skill stub: front matter, the four headings, the capability.

The full prose is deferred to FEAT-61; what the registry validates today is
the core's skill format: ``name`` and ``description`` in the front matter,
then ``## When to use``, ``## Pieces``, ``## Judging the result`` and
``## Pitfalls`` in order, with every capability id named in the body.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "packages" / "mermaid" / "skill" / "SKILL.md").read_text(encoding="utf-8")
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
    assert "mermaid.diagrama" in _body()


def test_the_skill_teaches_the_header_traps() -> None:
    """The traps the runner enforces are the ones the skill warns about."""
    body = _body()
    for token in ("fontFamily", "Ubuntu Sans", "CHROME_PATH", "PUPPETEER_SKIP_DOWNLOAD"):
        assert token in body, token


def test_no_reference_files_are_cited() -> None:
    """The stub cites no references/ file that does not exist."""
    cited = set(re.findall(r"references/([a-z0-9][a-z0-9-]*)\.md", _body()))
    for name in cited:
        assert (ROOT / "packages" / "mermaid" / "skill" / "references" / f"{name}.md").is_file()
