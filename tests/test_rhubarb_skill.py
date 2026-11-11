"""The rhubarb skill, manifest and README: what an agent and a person must read.

The skill is the only place an agent learns the package, so these tests pin its
front matter, the core's four headings in order, the capability id, the mouth
map verbatim, the phonetic flag and the Spanish note. The manifest checks pin
the python-env shape (no ``[engine.binary]``) and the one ``[[models]]`` pin a
pull relies on.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "rhubarb"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
README = (PACKAGE / "README.md").read_text(encoding="utf-8")
MANIFEST: dict[str, Any] = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
#: The mouth map, verbatim: X rest, A closed, B teeth, C open, D wide,
#: E round, F pursed, G teeth on lip, H tongue.
MOUTH_MAP = {
    "X": "rest",
    "A": "closed",
    "B": "teeth",
    "C": "open",
    "D": "wide",
    "E": "round",
    "F": "pursed",
    "G": "teeth on lip",
    "H": "tongue",
}
COMMAND = "rhubarb -r phonetic -f json --dialogFile <dialogue> <voice.wav> -o mouths.json"


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
    assert meta["name"] == "rhubarb"
    assert DESCRIPTION_MIN <= len(meta["description"]) <= DESCRIPTION_MAX


def test_the_four_headings_appear_in_order() -> None:
    _meta, body = _front_matter()
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_skill_names_the_capability_and_its_inputs() -> None:
    _meta, body = _front_matter()
    assert "rhubarb.mouths" in body
    for name in MANIFEST["capabilities"]["mouths"]["inputs"]:
        assert name in body, name


def test_the_skill_ports_the_mouth_map_verbatim() -> None:
    """Every letter with its shape, as the lab's table spells it."""
    _meta, body = _front_matter()
    for letter, shape in MOUTH_MAP.items():
        row = re.search(rf"^\|\s*`{letter}`\s*\|\s*([a-z ]+?)\s*\|$", body, re.MULTILINE)
        assert row is not None, f"no mouth-map row for {letter}"
        assert row.group(1) == shape, (letter, row.group(1))


def test_the_skill_carries_the_command_the_flag_and_the_spanish_note() -> None:
    _meta, body = _front_matter()
    assert COMMAND in body
    assert "psycho" not in body
    assert "Spanish" in body
    assert "English-only" in body
    assert "pocketSphinx" in body
    assert "runner_failed" in body


def test_the_skill_points_at_the_reference_character() -> None:
    """The approved reference is described by its contents, not a lab path."""
    _meta, body = _front_matter()
    assert "fox" in body
    assert "mouths.json" in body
    assert "prueba-personaje" not in SKILL
    assert "/home/jheisonmblivecom" not in SKILL


def test_the_skill_ships_no_references_directory() -> None:
    """The plan keeps it compact: the map lives in the skill itself."""
    assert not (PACKAGE / "skill" / "references").exists()


def test_the_manifest_is_a_python_env_client_not_a_binary_package() -> None:
    assert MANIFEST["name"] == "rhubarb"
    assert MANIFEST["facet"] == "video"
    assert MANIFEST["engine"] == {"type": "python-env", "python": "3.12"}
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    assert "binary" not in MANIFEST["engine"]
    assert "server" not in MANIFEST["engine"]


def test_the_capability_is_text_with_the_generic_viewer() -> None:
    capability = MANIFEST["capabilities"]["mouths"]
    assert capability["kind"] == "text"
    assert capability["preview"] == {"viewer": "generic"}
    inputs = capability["inputs"]
    assert set(inputs) == {"voice", "dialogue"}
    for name in ("voice", "dialogue"):
        assert inputs[name]["type"] == "path"
        assert inputs[name]["required"] is True
    assert "--dialogFile" in inputs["dialogue"]["description"]


def test_the_licence_covers_the_tool_and_the_zip() -> None:
    assert [(item["subject"], item["spdx"]) for item in MANIFEST["licenses"]] == [
        ("rhubarb-lip-sync", "MIT")
    ]
    assert MANIFEST["models"][0]["spdx"] == "MIT"


def test_the_requirements_fit_the_reference_machine() -> None:
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is False
    assert requirements["exclusive"] is True
    assert requirements["platforms"] == ["linux"]


def test_the_package_is_registered_in_the_index() -> None:
    names = [package["name"] for package in INDEX["packages"]]
    assert "rhubarb" in names


def test_the_package_has_its_own_uv_project() -> None:
    assert (PACKAGE / "pyproject.toml").is_file()
    assert (PACKAGE / "uv.lock").is_file()


def test_the_readme_documents_the_pin_the_command_and_the_rejections() -> None:
    """The page a person reads: the zip pin, the engine choice, Ditto rejected."""
    assert MANIFEST["models"][0]["url"] in README
    assert MANIFEST["models"][0]["sha256"] in README
    assert "-r phonetic" in README
    assert "python-env" in README
    assert "engine.binary" in README
    assert "Ditto" in README
    assert "uncanny valley" in README
    assert "fox" in README
    assert "prueba-personaje" not in README
    assert "/home/jheisonmblivecom" not in README
