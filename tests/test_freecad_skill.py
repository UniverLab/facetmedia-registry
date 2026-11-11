"""The freecad skill: front matter, the four headings, the capability and its reference.

The skill must name ``freecad.drawing`` with the script/part shape, cite the
wrapper reference by path, and that reference must carry the wrapper contract
the runner ports from the lab.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "freecad"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
#: A cited reference's own name, so the test resolves it under ``references/``.
REFERENCE_RE = re.compile(r"references/([a-z0-9][a-z0-9-]*)\.md")


def _body() -> str:
    _first, _second, body = SKILL.split("---", 2)
    return body


def test_the_front_matter_parses_in_the_core_format() -> None:
    first, second, _rest = SKILL.split("---", 2)
    assert first == ""
    frontmatter = second.strip().splitlines()
    assert "name: freecad" in frontmatter
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


def test_the_body_names_the_capability_and_the_script_part_shape() -> None:
    body = _body()
    assert "freecad.drawing" in body
    assert "script" in body
    assert "part" in body


def test_the_skill_cites_the_wrapper_reference() -> None:
    assert "references/wrapper.md" in SKILL


def test_the_wrapper_reference_carries_the_contract() -> None:
    reference = (PACKAGE / "skill" / "references" / "wrapper.md").read_text(encoding="utf-8")
    assert reference.strip()
    for token in ("--pass", "traceback", "wslpath", "FREECAD_EXE", "<name>.pdf"):
        assert token in reference


def test_every_cited_reference_exists() -> None:
    citations = REFERENCE_RE.findall(_body())
    assert citations
    for name in citations:
        reference = PACKAGE / "skill" / "references" / f"{name}.md"
        assert reference.is_file(), name
        assert reference.read_text(encoding="utf-8").strip(), name
