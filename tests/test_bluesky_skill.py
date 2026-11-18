"""The bluesky skill teaches the send and its authentication.

The skill is the only place an agent learns the package, so these tests
pin what a person reads: the front matter and the four headings the core
requires in order, the capability id ``bluesky.post``, the authentication
section (what the user creates and where, the exact secret names and
commands, the doctor confirmation, the usual failures), and the sources
file with the official AT Protocol and Bluesky docs behind the rules.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "bluesky"
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
    assert "name: bluesky" in frontmatter
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


def test_the_body_names_the_capability_and_the_piece() -> None:
    body = _body()
    assert "bluesky.post" in body
    for token in ("posts", "images", "alt", "card-url", "thread"):
        assert token in body, token


def test_the_auth_section_names_secrets_commands_and_confirmation() -> None:
    body = _body()
    assert "## Authentication" in body
    assert "App passwords" in body
    assert "handle" in body and "app-password" in body
    assert "facet secret set bluesky handle" in body
    assert "facet secret set bluesky app-password" in body
    assert "facet doctor post --full" in body


def test_the_auth_section_never_trades_in_secrets() -> None:
    flat = " ".join(_body().split())
    assert "never asks" in flat.lower() or "never ask" in flat.lower()
    assert "never runs `facet secret set` with a value" in flat


def test_the_sources_file_cites_the_official_docs() -> None:
    assert (PACKAGE / "skill" / "references" / "sources.md").is_file()
    for url in (
        "https://bsky.network/docs/bluesky-api",
        "https://atproto.com/specs/xrpc",
        "https://bsky.app/settings/app-passwords",
    ):
        assert url in SOURCES, url
