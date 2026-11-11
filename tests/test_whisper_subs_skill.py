"""The whisper-subs skill teaches the sidecar conversion, not transcription.

The skill is the only place an agent learns the package, so these tests pin
what a person reads: the front matter and the four headings the core requires
in order, the capability id ``whisper-subs.subtitulos`` with the srt/vtt
tokens, the extraction-first workflow through the packages that exist in this
registry (ffmpeg.convert and whisper.transcribe), the handoff to
``hyperframes.narrated`` — which reads whisper SRT — and that no references
directory ships.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "whisper-subs"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
MAX_DESCRIPTION = 200


def _body() -> str:
    _first, _second, body = SKILL.split("---", 2)
    return body


def test_the_front_matter_parses_in_the_core_format() -> None:
    first, second, _rest = SKILL.split("---", 2)
    assert first == ""
    frontmatter = second.strip().splitlines()
    assert "name: whisper-subs" in frontmatter
    description = next(
        line.removeprefix("description:").strip()
        for line in frontmatter
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= MAX_DESCRIPTION


def test_the_four_headings_appear_in_order() -> None:
    body = _body()
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_body_names_the_capability_and_both_formats() -> None:
    body = _body()
    assert "whisper-subs.subtitulos" in body
    assert "srt" in body and "vtt" in body
    assert "WEBVTT" in body
    assert "00:00:01,500" in body and "00:00:01.500" in body


def test_the_body_cites_only_packages_that_exist() -> None:
    body = _body()
    for capability in ("whisper.transcribe", "ffmpeg.convert", "hyperframes.narrated"):
        assert capability in body, capability


def test_the_body_carries_the_extraction_first_workflow() -> None:
    body = _body()
    assert "extraction first" in body
    assert "subtitles" in body


def test_no_references_dir_ships() -> None:
    assert not (PACKAGE / "skill" / "references").exists()
