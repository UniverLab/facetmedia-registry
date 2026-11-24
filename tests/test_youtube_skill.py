"""The youtube skill teaches upload, provenance disclosure and authentication."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "youtube"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
SOURCES = (PACKAGE / "skill" / "references" / "sources.md").read_text(encoding="utf-8")
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
    assert "name: youtube" in frontmatter
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


def test_the_body_names_the_capability_and_inputs() -> None:
    body = _body()
    assert "youtube.upload" in body
    for token in ("video", "title", "description", "category", "privacy", "made-for-kids"):
        assert token in body, token


def test_the_auth_guide_covers_setup_signin_and_confirmation() -> None:
    body = _body()
    assert "## Authentication" in body
    flat = " ".join(body.split())
    assert "Google Cloud" in body
    assert "YouTube Data API" in body
    assert "OAuth consent screen" in body
    assert "Desktop app" in body or "desktop" in flat.lower()
    assert "Testing" in body
    assert "refresh token" in flat.lower()
    assert "brand channel" in flat.lower()
    assert "facet auth login youtube" in body
    assert "facet auth youtube" in body
    assert "facet doctor post --full" in body


def test_the_auth_section_never_trades_in_secrets() -> None:
    flat = " ".join(_body().split()).lower()
    assert "never asks" in flat or "never ask" in flat
    assert "never runs" in flat or "never run" in flat
    assert "paste" in flat or "conversation" in flat


def test_the_auth_section_names_usual_failures() -> None:
    body = _body()
    assert "Usual failures" in body or "usual failures" in body.lower()
    assert "thumbnail" in body.lower()


def test_the_sources_file_cites_youtube_and_oauth_docs() -> None:
    assert (PACKAGE / "skill" / "references" / "sources.md").is_file()
    for url in (
        "https://developers.google.com/youtube/v3/docs/videos/insert",
        "https://developers.google.com/youtube/v3/docs/videos/list",
        "https://developers.google.com/youtube/v3/docs/thumbnails/set",
        "https://developers.google.com/youtube/v3/guides/auth/installed-apps",
        "https://developers.google.com/identity/protocols/oauth2",
    ):
        assert url in SOURCES, url
