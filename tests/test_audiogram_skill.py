"""The audiogram skill teaches the one capability and its editorial rules.

The skill is the only place an agent learns the package, so these tests
pin what a person reads: the front matter and the four headings the
core requires in order, the capability id ``audiogram.render``, the
style and aspect enums, the card rules, and the references file behind
them.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "audiogram"
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
    assert "name: audiogram" in frontmatter
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


def test_the_body_names_the_capability_and_the_visualizer_styles() -> None:
    body = _body()
    assert "audiogram.render" in body
    for style in ("bars", "waveform"):
        assert style in body, style
    for aspect in ("16:9", "9:16", "1:1"):
        assert aspect in body, aspect


def test_the_body_teaches_the_card_rules() -> None:
    body = _body()
    assert "cover" in body
    assert "title" in body
    assert "accent" in body
    assert "background" in body
    assert "preview" in body
    assert "doctor" in body


def test_the_references_file_pins_versions_and_licences() -> None:
    refs = (PACKAGE / "skill" / "references" / "sources.md").read_text(encoding="utf-8")
    for source in ("ffmpeg.org", "imageio-ffmpeg", "numpy.org", "soundfile", "pillow"):
        assert source in refs, source
    for pin in ("0.6.0", "2.5.4", "0.13.1", "13.0.0"):
        assert pin in refs, pin
    for spdx in ("BSD-2-Clause", "GPL-3.0-or-later", "BSD-3-Clause", "MIT-CMU"):
        assert spdx in refs, spdx


def test_the_package_readme_documents_the_piece_fields() -> None:
    readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
    assert "audiogram.render" in readme
    for field in (
        "audio",
        "style",
        "aspect",
        "cover",
        "title",
        "background",
        "accent",
        "fps",
        "crf",
    ):
        assert field in readme, field
