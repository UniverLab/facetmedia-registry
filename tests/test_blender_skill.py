"""The blender skill teaches the scripted scenes, their examples and the assets.

The skill is the only place an agent learns the package, so these tests pin
what a person reads: the front matter and the four headings the core requires
in order, the three capability ids v1 ships, the statement of who owns what
(facet the output, the script every creative choice), the three examples, and
the one reference the skill cites.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
EXAMPLES = PACKAGE / "examples"
REFERENCES = PACKAGE / "skill" / "references"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
CAPABILITIES = ("blender.scene", "blender.animation", "blender.assets")
OLD_CAPABILITIES = ("blender.photo", "blender.product", "blender.tour")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
#: The examples the skill presents as starting points, folder and piece.
EXAMPLES_SHIPPED = (
    ("study", "study.toml", "study.py"),
    ("product", "product.toml", "product.py"),
    ("tour", "tour.toml", "tour.py"),
)
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


def _flat() -> str:
    """The body with every run of whitespace collapsed, for phrase assertions."""
    return " ".join(_front_matter()[1].split())


def test_skill_front_matter_and_headings_order() -> None:
    """The core's contract: name=blender, a 20-200 description, four headings."""
    meta, body = _front_matter()
    assert meta["name"] == "blender"
    assert DESCRIPTION_MIN <= len(meta["description"]) <= DESCRIPTION_MAX
    assert "\n" not in meta["description"]
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_skill_names_the_three_capabilities_and_no_preset() -> None:
    """v1 is scene, animation and assets; the removed ids are never cited."""
    _, body = _front_matter()
    for capability in CAPABILITIES:
        assert capability in body, capability
    for old in OLD_CAPABILITIES:
        assert old not in body, old
    assert set(MANIFEST["capabilities"]) == {"scene", "animation", "assets"}


def test_the_skill_states_who_owns_what() -> None:
    """An agent must know facet owns the output and the script the look."""
    flat = _flat()
    assert "facet owns only the output" in flat
    assert "The script owns every creative choice" in flat
    assert "FACET_PIECE_DIR" in flat and "FACET_ASSETS" in flat
    assert "scene.camera" in flat
    assert "copy and edit" in flat


def test_the_skill_points_at_the_three_examples() -> None:
    """Each example folder ships its piece and its script, and the skill says so."""
    flat = _flat()
    for folder, piece, script in EXAMPLES_SHIPPED:
        assert (EXAMPLES / folder / piece).is_file(), piece
        assert (EXAMPLES / folder / script).is_file(), script
        assert folder in flat, folder
    # The minimal scene example stays as it is and is still named.
    assert "examples/scene/" in flat


def test_the_skill_keeps_the_glass_and_metal_lessons() -> None:
    """The two failures the functional test found, as the pitfalls that fix them."""
    flat = _flat()
    assert 'surface_render_method = "BLENDED"' in SKILL
    assert "black box" in flat
    assert "softbox" in flat.lower()
    assert "0.001" in flat


def test_every_reference_the_skill_cites_exists() -> None:
    """A cited reference that is not on disk sends the reader nowhere."""
    cited = set(REFERENCE_RE.findall(SKILL))
    assert cited, "the skill cites at least one reference"
    for name in cited:
        path = REFERENCES / f"{name}.md"
        assert path.is_file(), name
        assert path.stat().st_size > 0, name
    assert (REFERENCES / "scene.md").is_file()


def test_the_removed_references_are_gone() -> None:
    """The tour and people/cars references went with their capabilities."""
    for name in ("tour.md", "people-cars.md"):
        assert not (REFERENCES / name).exists(), name


def test_the_skill_never_cites_mannequin() -> None:
    """Mannequin appears in neither lab source, so the skill never names it."""
    assert "mannequin" not in SKILL.lower()
