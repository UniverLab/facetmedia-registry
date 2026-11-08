"""The acestep skill teaches the bed, the caption rules and the loudness.

The skill is the only place an agent learns the package, so these tests pin
what a person reads: the front matter and the four headings the core requires
in order, the capability id ``acestep.bed``, and the caption guidance that
keeps drums and voice out of a bed.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "acestep"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200


def _front_matter() -> tuple[dict[str, str], str]:
    """The skill's front matter and body, split the way the core parses it."""
    first, second, *rest = SKILL.split("---", 2)
    assert first == "" and second.strip().startswith("name:")
    meta: dict[str, str] = {}
    for line in second.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, rest[0]


def test_skill_front_matter_and_headings_order() -> None:
    """The core's contract: name=acestep, a 20-200 description, four headings."""
    meta, body = _front_matter()
    assert meta["name"] == "acestep"
    assert DESCRIPTION_MIN <= len(meta["description"]) <= DESCRIPTION_MAX
    assert "\n" not in meta["description"]
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_skill_names_the_capability_and_the_inputs() -> None:
    _, body = _front_matter()
    assert "acestep.bed" in body
    for name in MANIFEST["capabilities"]["bed"]["inputs"]:
        assert name in body, name


def test_the_skill_states_the_caption_rules_and_the_voice_refusal() -> None:
    """The drums guidance and the sung-music verdict are not left to the README."""
    _, body = _front_matter()
    assert "No drums, no percussion, no bass beat, no synthesizers" in body
    assert re.search(r"acoustic instruments", body, re.IGNORECASE)
    assert re.search(r"sung", body, re.IGNORECASE)
    assert re.search(r"voice", body, re.IGNORECASE)
