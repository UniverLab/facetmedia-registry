"""The pillow skill teaches the three ops and their decided rules.

The skill is the only place an agent learns the package, so these tests
pin what a person reads: the front matter and the four headings the core
requires in order, the capability id ``pillow.base``, the formato/modo
enums and the jpeg-flatten rule, the resize rules, and the hoja
tile-and-divider layout for review boards.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "pillow"
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
    assert "name: pillow" in frontmatter
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


def test_the_body_names_the_capability_and_the_ops() -> None:
    body = _body()
    assert "pillow.base" in body
    for op in ("convertir", "redimensionar", "hoja"):
        assert op in body, op


def test_the_skill_teaches_the_formato_modo_and_jpeg_rule() -> None:
    body = _body()
    for token in ("png", "jpeg", "webp", "RGB", "RGBA", "L"):
        assert token in body, token
    assert "RGBA" in body and "jpeg" in body
    assert "white" in body  # the alpha flatten onto white


def test_the_skill_teaches_the_resize_and_hoja_rules() -> None:
    body = _body()
    assert "Lanczos" in body
    assert "aspect" in body
    assert "floor" in body
    assert "divider" in body or "dividers" in body
