"""The linkedin skill: the agent's auth guide, with its sources."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "linkedin"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
SOURCES = (PACKAGE / "skill" / "references" / "sources.md").read_text(encoding="utf-8")


def test_the_skill_exists_with_front_matter() -> None:
    assert (PACKAGE / "skill" / "SKILL.md").is_file()
    assert SKILL.startswith("---\nname: linkedin\n")
    assert "description:" in SKILL.split("---", 2)[1]


def test_the_skill_names_the_organization_post_flow() -> None:
    lowered = SKILL.lower()
    assert "organization" in lowered
    assert "multiimage" in lowered
    assert "public" in lowered and "draft" in lowered


def test_the_skill_states_the_v1_scope() -> None:
    lowered = SKILL.lower()
    assert "images only" in lowered
    assert "personal" in lowered
    assert "never schedules" in lowered


def test_the_skill_guides_the_sign_in_without_touching_a_secret() -> None:
    lowered = SKILL.lower()
    for step in (
        "developer portal",
        "w_organization_social",
        "r_organization_social",
        "administrator",
        "redirect",
        "facet secret set linkedin",
        "facet auth linkedin",
        "facet auth login linkedin",
        "doctor",
    ):
        assert step in lowered, step
    assert "never asks the user to paste" in lowered


def test_the_skill_warns_about_the_usual_failures() -> None:
    lowered = SKILL.lower()
    assert "not enough" in lowered and "permissions" in lowered
    assert "company page role" in lowered
    assert "never re-send" in lowered


def test_the_skill_names_the_piece_shapes() -> None:
    assert "linkedin.post" in SKILL
    assert "author" in SKILL
    assert "urn:li:organization" in SKILL
    assert "post.toml" in SKILL


MIN_SOURCES = 4


def test_the_sources_cite_the_developer_docs_in_own_words() -> None:
    rows = [line for line in SOURCES.splitlines() if line.startswith("| https://")]
    assert len(rows) >= MIN_SOURCES
    assert all("learn.microsoft.com" in row for row in rows)
    assert all("LinkedIn" in row for row in rows)
    lowered = SOURCES.lower()
    assert "no wording taken" in lowered
    assert "x-restli-id" in lowered
