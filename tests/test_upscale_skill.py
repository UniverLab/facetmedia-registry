"""The upscale skill teaches the capability, models, 2x Lanczos rule, and doctor."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "upscale"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
SOURCES = (PACKAGE / "skill" / "references" / "sources.md").read_text(encoding="utf-8")
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200


def _body() -> str:
    _first, _second, body = SKILL.split("---", 2)
    return body


def test_front_matter_matches_core_format() -> None:
    first, second, _rest = SKILL.split("---", 2)
    assert first == ""
    lines = second.strip().splitlines()
    assert "name: upscale" in lines
    description = next(
        line.removeprefix("description:").strip()
        for line in lines
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX


def test_four_headings_appear_in_order() -> None:
    body = _body()
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_skill_covers_capability_models_and_2x_rule() -> None:
    body = _body()
    assert "upscale.enhance" in body
    for model in ("realesrgan-x4plus", "realesrgan-x4plus-anime", "realesr-animevideov3"):
        assert model in body
    assert "LANCZOS" in body
    assert "doctor" in body
    assert "Real-ESRGAN" in SOURCES
