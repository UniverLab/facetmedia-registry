"""The video-ops skill teaches transcode, mux-audio, frame, and verification."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "video-ops"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200


def _body() -> str:
    _first, _second, body = SKILL.split("---", 2)
    return body


def test_front_matter_parses_in_core_format() -> None:
    first, second, _rest = SKILL.split("---", 2)
    assert first == ""
    frontmatter = second.strip().splitlines()
    assert "name: video-ops" in frontmatter
    description = next(
        line.removeprefix("description:").strip()
        for line in frontmatter
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX


def test_four_headings_appear_in_order() -> None:
    body = _body()
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_body_names_all_three_capabilities_and_key_flags() -> None:
    body = _body()
    for cap in ("video-ops.transcode", "video-ops.mux-audio", "video-ops.frame"):
        assert cap in body
    for token in ("crf", "max-width", "at-s", "faststart", "libx264", "ffprobe"):
        assert token in body


def test_sources_file_exists_and_names_upstream_projects() -> None:
    sources = PACKAGE / "skill" / "references" / "sources.md"
    assert sources.is_file()
    text = sources.read_text(encoding="utf-8")
    for token in ("FFmpeg", "imageio-ffmpeg", "Pillow"):
        assert token in text
