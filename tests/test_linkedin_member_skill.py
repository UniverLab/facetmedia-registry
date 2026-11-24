"""The linkedin-member skill: the agent's auth guide, with its sources."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "linkedin-member"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
SOURCES = (PACKAGE / "skill" / "references" / "sources.md").read_text(encoding="utf-8")


def test_the_skill_exists_with_front_matter() -> None:
    assert (PACKAGE / "skill" / "SKILL.md").is_file()
    assert SKILL.startswith("---\nname: linkedin-member\n")
    assert "description:" in SKILL.split("---", 2)[1]


def test_the_skill_contrasts_organization_and_personal_accounts() -> None:
    lowered = SKILL.lower()
    assert "linkedin" in lowered
    assert "organization" in lowered
    assert "personal" in lowered
    assert "under their own name" in lowered or "under their name" in lowered


def test_the_skill_guides_the_sign_in_without_touching_a_secret() -> None:
    lowered = SKILL.lower()
    for step in (
        "developer portal",
        "share on linkedin",
        "openid connect",
        "w_member_social",
        "openid profile w_member_social",
        "http://localhost:8080/callback",
        "facet secret set linkedin-member",
        "facet auth login linkedin-member",
        "doctor",
    ):
        assert step in lowered, step
    assert "never asks the user to paste" in lowered


def test_the_skill_names_the_piece_shapes_and_pitfalls() -> None:
    assert "linkedin-member.post" in SKILL
    assert "post.toml" in SKILL
    lowered = SKILL.lower()
    assert "refresh-token" in lowered or "refresh token" in lowered
    assert "unknown" in lowered
    assert "never re-send" in lowered


MIN_SOURCES = 4


def test_the_sources_cite_the_developer_docs_in_own_words() -> None:
    rows = [line for line in SOURCES.splitlines() if line.startswith("| https://")]
    assert len(rows) >= MIN_SOURCES
    assert all("learn.microsoft.com" in row for row in rows)
    assert all("LinkedIn" in row for row in rows)
    lowered = SOURCES.lower()
    assert "no wording taken" in lowered
    assert "x-restli-id" in lowered
