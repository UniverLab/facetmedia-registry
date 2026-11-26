"""The x skill teaches the send, its cost and its authentication.

The skill is the only place an agent learns the package, so these tests
pin what a person reads: the front matter and the four headings the core
requires in order, the capability id ``x.post``, the authentication
section (what the user creates and where, the exact secret names and
commands, the doctor confirmation, the usual failures, the never-paste
rule), and the sources file with the docs.x.com pages behind the rules.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "x"
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
    assert "name: x" in frontmatter
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
    assert "x.post" in body
    for token in ("posts", "images", "alt", "gif", "thread"):
        assert token in body, token


def test_the_auth_section_names_secrets_commands_and_confirmation() -> None:
    body = _body()
    assert "## Authentication" in body
    assert "Automated App" in body
    assert "confidential client" in body
    assert "Read and write" in body
    assert "Website URL" in body
    assert "localhost" in body
    assert "http://127.0.0.1:8080/callback" in body
    flat = " ".join(body.split())
    assert "client-id" in flat and "refresh token" in flat
    assert "consumer-key" not in body and "access-token-secret" not in body
    assert "facet auth login x" in body
    assert "facet secret set x client-id" in body
    assert "facet secret set x client-secret" in body
    assert "facet doctor post --full" in body
    assert "https://console.x.com" in body


def test_the_auth_section_never_trades_in_secrets() -> None:
    flat = " ".join(_body().split())
    assert "never asks" in flat.lower() or "never ask" in flat.lower()
    assert "`facet auth` with a value" in flat


def test_the_auth_section_names_credits_scopes_and_failures() -> None:
    flat = " ".join(_body().split())
    assert "credit" in flat.lower()
    assert "offline.access" in flat.lower()
    assert "no credits" in flat.lower() or "credits ran out" in flat.lower()
    assert "wrong account" in flat.lower()


def test_the_body_shows_the_cost_before_the_send() -> None:
    body = _body()
    assert "$0.015" in body and "$0.200" in body
    assert "$0.005" in body and "$0.010" in body
    assert "23" in body


def test_the_sources_file_cites_the_official_docs() -> None:
    assert (PACKAGE / "skill" / "references" / "sources.md").is_file()
    for url in (
        "https://docs.x.com/x-api/getting-started/pricing",
        "https://docs.x.com/fundamentals/counting-characters",
        "https://docs.x.com/x-api/posts/create-post",
        "https://docs.x.com/x-api/posts/get-posts-by-ids",
        "https://docs.x.com/x-api/media/quickstart/media-upload-chunked",
        "https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code",
        "https://docs.x.com/fundamentals/authentication/oauth-2-0/refresh-token",
        "https://docs.x.com/fundamentals/authentication/oauth-2-0/user-context",
    ):
        assert url in SOURCES, url
