"""The svganim skill stub: front matter, the four headings, the capability.

The skill is a stub in this change (the full prose is FEAT-63), but the core
validates its shape: ``name`` and ``description`` in the front matter, then
``## When to use``, ``## Pieces``, ``## Judging the result`` and
``## Pitfalls`` in order, with the capability id named in the body.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "svganim"
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
    assert "name: svganim" in frontmatter
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


def test_the_body_names_the_capability_and_the_text_rule() -> None:
    body = _body()
    assert "svganim.bake" in body
    assert "opentype.js" in body
    assert "<text>" in body
    assert "@keyframes" in body


def test_the_skill_cites_the_build_banners_reference() -> None:
    assert "references/build-banners.md" in SKILL


def test_the_build_banners_reference_carries_the_recipe() -> None:
    reference = (PACKAGE / "skill" / "references" / "build-banners.md").read_text(encoding="utf-8")
    assert reference.strip()
    for token in (
        "loadSync",
        "toPathData",
        "kerning",
        "data:image",
        "argv[2]",
        "@keyframes",
    ):
        assert token in reference
    for token in ("process.argv", "process.stdout.write", "require("):
        assert token in reference
