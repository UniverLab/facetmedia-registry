"""The tiktok skill: the agent's auth guide, with its sources."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "tiktok"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
SOURCES = (PACKAGE / "skill" / "references" / "sources.md").read_text(encoding="utf-8")


def test_the_skill_exists_with_front_matter() -> None:
    assert (PACKAGE / "skill" / "SKILL.md").is_file()
    assert SKILL.startswith("---\nname: tiktok\n")
    assert "description:" in SKILL.split("---", 2)[1]


def test_the_skill_names_the_inbox_draft_flow() -> None:
    lowered = SKILL.lower()
    assert "inbox" in lowered
    assert "draft" in lowered
    assert "paste" in lowered and "caption" in lowered


def test_the_skill_guides_the_sign_in_without_touching_a_secret() -> None:
    lowered = SKILL.lower()
    for step in (
        "login kit",
        "content posting api",
        "video.upload",
        "redirect",
        "verif",
        "facet auth tiktok",
        "doctor",
    ):
        assert step in lowered, step
    assert "never asks the user to paste" in lowered


def test_the_skill_warns_about_the_usual_failures() -> None:
    lowered = SKILL.lower()
    assert "url_ownership_unverified" in lowered or "verified" in lowered
    assert "audit" in lowered
    assert "public" in lowered


def test_the_skill_names_the_piece_shapes() -> None:
    assert "tiktok.post" in SKILL
    assert "caption" in SKILL
    assert "photos" in SKILL
    assert "inbox.toml" in SKILL


MIN_SOURCES = 4


def test_the_sources_cite_the_developer_docs_in_own_words() -> None:
    rows = [line for line in SOURCES.splitlines() if line.startswith("| https://")]
    assert len(rows) >= MIN_SOURCES
    assert all("developers.tiktok.com" in row for row in rows)
    assert all("TikTok" in row for row in rows)
    lowered = SOURCES.lower()
    assert "no wording taken" in lowered
    assert "send_to_user_inbox" in lowered or "SEND_TO_USER_INBOX" in SOURCES
