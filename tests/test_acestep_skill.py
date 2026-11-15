"""The acestep skill teaches the bed, the caption rules and the loudness.

The skill is the only place an agent learns the package, so these tests pin
what a person reads: the front matter and the four headings the core requires
in order, the capability id ``acestep.bed``, the caption guidance that keeps
drums and voice out of a bed, the approved examples with their WAVs, the
under-voice levels, and the references the skill cites.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "acestep"
EXAMPLES = PACKAGE / "examples"
REFERENCES = PACKAGE / "skill" / "references"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
#: The approved pieces that ship, each as a ``.toml`` and a ``.wav``.
APPROVED = ("baroque-allegro", "romantic-nocturne")
#: The line the caption ends with, verbatim, plus the lab's electronic-sounds tail.
NO_DRUMS = "No drums, no percussion, no bass beat, no synthesizers"
#: A reference the skill cites, as ``references/<name>.md``.
REFERENCE_RE = re.compile(r"references/([a-z0-9][a-z0-9-]*)\.md")


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
    assert NO_DRUMS in body
    assert re.search(r"acoustic instruments", body, re.IGNORECASE)
    assert re.search(r"sung", body, re.IGNORECASE)
    assert re.search(r"voice", body, re.IGNORECASE)


def test_the_skill_cites_the_approved_examples() -> None:
    """Both approved pieces are named in the skill, not only left on disk."""
    _, body = _front_matter()
    for piece in APPROVED:
        assert f"examples/{piece}.toml" in body, piece


def test_the_examples_are_runnable_bed_pieces() -> None:
    """Each example parses, stays inside ``acestep.bed`` and ships its WAV."""
    bed_inputs = MANIFEST["capabilities"]["bed"]["inputs"]
    name_pattern = bed_inputs["name"]["pattern"]
    max_duration = bed_inputs["duration"]["max"]
    for piece in APPROVED:
        data = tomllib.loads((EXAMPLES / f"{piece}.toml").read_text(encoding="utf-8"))
        inputs = data["inputs"]
        assert set(inputs) <= set(bed_inputs), piece
        caption = inputs["caption"]
        assert NO_DRUMS in caption, piece
        assert "no electronic sounds" in caption, piece
        assert re.fullmatch(name_pattern, inputs["name"]), piece
        assert inputs["name"] == piece, piece
        assert 0 < inputs["duration"] <= max_duration, piece
        wav = EXAMPLES / f"{piece}.wav"
        assert wav.is_file(), piece
        assert wav.stat().st_size > 0, piece


def test_the_skill_ports_the_under_voice_levels_and_the_licence() -> None:
    """The narrado contract and the MIT verdict survive the port as numbers."""
    _, body = _front_matter()
    assert "MIT" in body
    assert "ducking" in body
    assert "-12.0" in body
    assert "-16" in body
    assert "true-peak-db" in body
    # The lab's low-energy range that separates the approved classics.
    assert "2.5" in body


def test_every_reference_the_skill_cites_exists() -> None:
    """A cited reference that is not on disk sends the reader nowhere."""
    _, body = _front_matter()
    cited = set(REFERENCE_RE.findall(body))
    assert cited, "the skill cites at least one reference"
    for name in cited:
        path = REFERENCES / f"{name}.md"
        assert path.is_file(), name
        assert path.stat().st_size > 0, name


def test_the_caption_reference_carries_both_approved_captions() -> None:
    """The reference ports the lab's captions verbatim, tails included."""
    text = (REFERENCES / "captions.md").read_text(encoding="utf-8")
    assert NO_DRUMS in text
    for piece in APPROVED:
        data = tomllib.loads((EXAMPLES / f"{piece}.toml").read_text(encoding="utf-8"))
        assert data["inputs"]["caption"] in text, piece
