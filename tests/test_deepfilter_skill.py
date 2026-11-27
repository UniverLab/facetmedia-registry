"""The deepfilter skill, example and docs: what an agent and a person must read.

The skill is the only place an agent learns the package, so these tests pin
its front matter, the core's four headings in order, the capability id, and
the chain the lab runs on a noisy take. The example checks pin the tagged
piece the registry suite consumes.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "deepfilter"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
README = (PACKAGE / "README.md").read_text(encoding="utf-8")
MANIFEST: dict[str, Any] = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
#: Where the skill's cited sources live, and the shape of one table row.
SOURCES = PACKAGE / "skill" / "references" / "sources.md"
SOURCE_ROWS = 2
SOURCE_COLUMNS = 4
EXAMPLE = PACKAGE / "examples" / "enhance.toml"


def _front_matter() -> tuple[dict[str, str], str]:
    """The skill's front matter and body, split the way the core parses it."""
    first, second, *rest = SKILL.split("---", 2)
    assert first == "" and second.strip().startswith("name:")
    meta: dict[str, str] = {}
    for line in second.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, rest[0]


def test_the_front_matter_parses_in_the_core_format() -> None:
    meta, _body = _front_matter()
    assert meta["name"] == "deepfilter"
    assert DESCRIPTION_MIN <= len(meta["description"]) <= DESCRIPTION_MAX


def test_the_four_headings_appear_in_order() -> None:
    _meta, body = _front_matter()
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_skill_names_the_capability_and_its_inputs() -> None:
    _meta, body = _front_matter()
    assert "deepfilter.enhance" in body
    for name in MANIFEST["capabilities"]["enhance"]["inputs"]:
        assert name in body, name


def test_the_skill_teaches_enhance_over_ffmpeg_clean() -> None:
    """The neural route is chosen over the classic one, and the reason is taught."""
    _meta, body = _front_matter()
    assert "ffmpeg.clean" in body
    assert "DeepFilterNet3" in body
    assert "48 kHz" in body


def test_the_skill_chains_enhance_normalize_and_mux() -> None:
    """The lab chain: denoise, then loudness, then the voice back under the picture."""
    _meta, body = _front_matter()
    assert "ffmpeg.normalize" in body
    assert "video-ops.mux-audio" in body
    chain = ("deepfilter.enhance", "ffmpeg.normalize", "video-ops.mux-audio")
    order = [body.index(token) for token in chain]
    assert order == sorted(order)


def test_the_skill_carries_the_flags_and_the_attenuation() -> None:
    _meta, body = _front_matter()
    assert "-a" in body
    assert "--pf" in body
    assert "atten-lim-db" in body
    assert "post-filter" in body


def test_the_skill_points_at_no_lab_paths() -> None:
    assert "prueba-" not in SKILL
    assert "/home/jheisonmblivecom" not in SKILL


def test_the_skill_ships_sources_for_the_guidance_it_teaches() -> None:
    _meta, body = _front_matter()
    assert "references/sources.md" in body
    assert SOURCES.is_file()
    rows = [
        line
        for line in SOURCES.read_text(encoding="utf-8").splitlines()
        if line.startswith("| https://")
    ]
    assert len(rows) == SOURCE_ROWS
    for row in rows:
        assert "| Hendrik Schröter |" in row
        assert "| MIT |" in row
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) == SOURCE_COLUMNS
        assert cells[3], row


def test_the_example_piece_is_tagged_with_a_fixture_beside_it() -> None:
    data = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert data["capability"] == "deepfilter.enhance"
    assert EXAMPLE.stem != data["capability"]
    audio = data["inputs"]["audio"]
    assert (EXAMPLE.parent / str(audio)).is_file()
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(data["inputs"]["name"]))


def test_the_skill_snippet_names_the_shipped_fixture() -> None:
    """The Pieces snippet is copy-pasteable: its audio file ships in examples."""
    assert 'audio = "voice-noisy.wav"' in SKILL
    assert (PACKAGE / "examples" / "voice-noisy.wav").is_file()


def test_the_readme_documents_the_pin_the_command_and_the_chain() -> None:
    """The page a person reads: the binary pin, the python-env choice, the chain."""
    assert MANIFEST["models"][0]["url"] in README
    assert MANIFEST["models"][0]["sha256"] in README
    assert "deep-filter -D -a" in README
    assert "python-env" in README
    assert "engine.binary" in README
    assert "ffmpeg.normalize" in README
    assert "video-ops.mux-audio" in README
    assert "/home/jheisonmblivecom" not in README
