"""The blender skill teaches the scenes, the asset contracts and the tour.

The skill is the only place an agent learns the package, so these tests pin
what a person reads: the front matter and the four headings the core requires
in order, every capability id (``blender.photo``, ``blender.product``,
``blender.assets``, ``blender.tour``), the two hyphenated input names
facet resolves, the tour example over the shipped glTF, and the two reference
files.
"""

from __future__ import annotations

import importlib.util
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
CAPABILITIES = ("blender.photo", "blender.product", "blender.assets", "blender.tour")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
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
    """The core's contract: name=blender, a 20-200 description, four headings."""
    meta, body = _front_matter()
    assert meta["name"] == "blender"
    assert DESCRIPTION_MIN <= len(meta["description"]) <= DESCRIPTION_MAX
    assert "\n" not in meta["description"]
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_capability_ids_and_hyphenated_inputs() -> None:
    """Every capability is named once, and the input names are hyphenated."""
    _, body = _front_matter()
    for capability in CAPABILITIES:
        assert capability in body, capability
    assert "people-blend" in body
    assert "cars-blend" in body
    # The manifest is the source of truth for the spelling facet resolves.
    for capability in ("photo", "tour"):
        inputs = MANIFEST["capabilities"][capability]["inputs"]
        assert "people-blend" in inputs, capability
        assert "cars-blend" in inputs, capability


def test_the_skill_keeps_the_lab_numbers_verbatim() -> None:
    """The timings and counts are ported, not summarised away."""
    _, body = _front_matter()
    for number in ("128-160 samples", "8-10 s per image", "~11 s"):
        assert number in body, number
    assert "240 frames at 1280x720 in ~100 s" in body
    for count in ("14 outfits", "6 pairs of shoes", "10 hairstyles", "23 skins"):
        assert count in body, count
    assert "40°" in body and "30°" in body


def test_the_skill_carries_both_placement_contracts() -> None:
    """The main page, not only a lazy-loaded reference, states the contract.

    ``-y`` facing, the floor people stand on, the after-dress order, the car's
    anchor at its base and the wall framing are what makes a placement work;
    an agent that reads only ``SKILL.md`` must still get them.
    """
    _, body = _front_matter()
    for token in ("-y", "floor", "after", "dress", "anchor", "1.5 m", "52°"):
        assert token in body, token
    assert "people-blend" in body and "cars-blend" in body


def test_the_skill_records_the_rejected_alternatives() -> None:
    """The verdicts the lab reached, so nobody re-proposes them."""
    _, body = _front_matter()
    for token in ("Kenney", "Sketchfab", "D5"):
        assert token in body, token
    assert "CC-BY" in body and "token" in body
    assert "closed GUI application" in body


def test_every_reference_the_skill_cites_exists() -> None:
    """A cited reference that is not on disk sends the reader nowhere."""
    _, body = _front_matter()
    cited = set(REFERENCE_RE.findall(body))
    assert cited, "the skill cites at least one reference"
    for name in cited:
        path = REFERENCES / f"{name}.md"
        assert path.is_file(), name
        assert path.stat().st_size > 0, name


def test_tour_toml_parses_model_glb() -> None:
    """The tour example parses and points at the glb that ships beside it."""
    piece = EXAMPLES / "tour.toml"
    assert piece.is_file()
    data = tomllib.loads(piece.read_text(encoding="utf-8"))
    inputs = data["inputs"]
    model = EXAMPLES / inputs["model"]
    assert model.resolve() == (EXAMPLES / "estudio.glb").resolve()
    assert model.is_file()
    # The lab's start/end triples, one { start, end } item each.
    assert inputs["azimuth"] == [{"start": -75, "end": -15}]
    assert inputs["elevation"] == [{"start": 55, "end": 40}]
    assert inputs["distance"] == [{"start": 14.0, "end": 10.5}]
    assert (inputs["focal"], inputs["seconds"], inputs["fps"]) == (30, 10, 24)


def test_tour_toml_is_a_runnable_tour_piece() -> None:
    """The example carries every input ``blender.tour`` reads, no extras."""
    data = tomllib.loads((EXAMPLES / "tour.toml").read_text(encoding="utf-8"))
    tour_inputs = set(MANIFEST["capabilities"]["tour"]["inputs"])
    assert set(data["inputs"]) <= tour_inputs
    assert {"model", "azimuth", "elevation", "distance", "focal", "seconds", "fps"} == set(
        data["inputs"]
    )


def test_references_exist() -> None:
    """Both references the skill cites are present and carry their contracts."""
    tour = REFERENCES / "tour.md"
    people = REFERENCES / "people-cars.md"
    for path in (tour, people):
        assert path.is_file(), path
        assert path.stat().st_size > 0, path
    tour_text = tour.read_text(encoding="utf-8")
    for token in ("BLENDER_EEVEE", "smooth", "FFMPEG", "H264", "1280x720"):
        assert token in tour_text, token
    people_text = people.read_text(encoding="utf-8")
    for token in ("people-blend", "cars-blend", "runner_failed", "not_found", "MPFB"):
        assert token in people_text, token


def test_the_skill_never_cites_mannequin() -> None:
    """Mannequin appears in neither lab source, so the skill never names it."""
    assert "mannequin" not in SKILL.lower()


def _load_escena():
    """The lab's material set, loaded without Blender: escena needs no bpy."""
    spec = importlib.util.spec_from_file_location("blender_escena", PACKAGE / "escena.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_lists_every_material_prefix() -> None:
    """The Pitfalls bullet names each accepted prefix, so the agent renames."""
    _, body = _front_matter()
    pitfalls = body.split("## Pitfalls", 1)[1]
    assert "piezas sin material" in pitfalls
    match = re.search(r"[Tt]he accepted prefixes are (.*?)\(the keys of", pitfalls, re.DOTALL)
    assert match is not None, "the Pitfalls bullet lists the accepted prefixes"
    listed = set(re.findall(r"`([a-z]+)`", match.group(1)))
    assert listed == set(_load_escena().MATERIALS)


def test_skill_never_asks_to_extend_materials() -> None:
    """The agent renames its piece; it never edits the package's MATERIALS."""
    assert "Add the prefix to" not in SKILL


def _dressing_example() -> dict:
    """The Dressing section's photo piece: the block that carries sky."""
    blocks = re.findall(r"```toml\n(.*?)```", SKILL, re.DOTALL)
    dressed = [tomllib.loads(block) for block in blocks if "\nsky =" in block]
    assert len(dressed) == 1, "one photo piece carries the dressing inputs"
    return dressed[0]["inputs"]


def test_the_dressing_example_uses_only_declared_inputs() -> None:
    """The example parses and stays inside the manifest: keys, fields, enum."""
    example = _dressing_example()
    declared = MANIFEST["capabilities"]["photo"]["inputs"]
    assert set(example) <= set(declared)
    assert {"model", "sky", "textures", "plants"} <= set(example)
    enum = set(declared["textures"]["items"]["prefix"]["values"])
    for name in ("sky", "textures", "plants"):
        items = declared[name]["items"]
        required = {key for key, item in items.items() if item.get("required")}
        defaults = {key for key, item in items.items() if "default" in item}
        assert set(items) == required | defaults
        for entry in example[name]:
            assert set(entry) <= set(items), (name, entry)
            assert required <= set(entry), (name, entry)
    assert {entry["prefix"] for entry in example["textures"]} <= enum


def test_the_dressing_example_fetches_before_rendering() -> None:
    """The assets piece that fetches the example's ids, with the lab default."""
    blocks = re.findall(r"```toml\n(.*?)```", SKILL, re.DOTALL)
    pieces = [tomllib.loads(block) for block in blocks if "assets" in block]
    assert len(pieces) == 1, "one blender.assets piece fetches the dressing set"
    entries = {entry["id"]: entry for entry in pieces[0]["inputs"]["assets"]}
    example = _dressing_example()
    wanted = {example["sky"][0]["id"]}
    wanted |= {entry["id"] for entry in example["textures"]}
    wanted |= {entry["id"] for entry in example["plants"]}
    assert wanted <= set(entries)
    for asset_id in wanted:
        assert entries[asset_id]["res"] in ("1k", "2k")
    assert "last part" in SKILL and "polyhaven.com" in SKILL
