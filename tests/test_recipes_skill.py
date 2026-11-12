"""The recipes skill teaches complete pieces, and every id it names resolves.

The skill is the only place an agent learns the recipes, so these tests pin
what a person reads: the front matter, the four headings the core requires
in order, one recipe per complete piece with the same chains the data file
carries, and that every named capability resolves against the packages in
this registry. The architectural render names ``blender.scene`` and the
study-photo example, never a photo preset, and no references directory ships.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "recipes"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
RECIPES = json.loads((PACKAGE / "recipes.json").read_text(encoding="utf-8"))["recipes"]
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
MAX_DESCRIPTION = 200

CHAINS = {
    "explainer-video": [
        "voicestudio.speak",
        "acestep.bed",
        "ffmpeg.normalize",
        "ffmpeg.mix",
        "whisper.transcribe",
        "whisper-subs.subtitles",
        "hyperframes.narrated",
    ],
    "architecture-render": ["cad.solid", "blender.assets", "blender.scene", "deck.page"],
    "voice-material": ["kokoro.speak", "acestep.bed", "deck.slides"],
    "tool-demo": ["demostage.demo", "deck.slides"],
}


def _body() -> str:
    _first, _second, body = SKILL.split("---", 2)
    return body


def _registry_capabilities() -> set[str]:
    """Every capability id declared by a package manifest in this registry."""
    capabilities: set[str] = set()
    for manifest_path in ROOT.glob("packages/*/package.toml"):
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        for name in manifest.get("capabilities", {}):
            capabilities.add(f"{manifest['name']}.{name}")
    return capabilities


def test_the_front_matter_parses_in_the_core_format() -> None:
    first, second, _rest = SKILL.split("---", 2)
    assert first == ""
    frontmatter = second.strip().splitlines()
    assert "name: recipes" in frontmatter
    description = next(
        line.removeprefix("description:").strip()
        for line in frontmatter
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= MAX_DESCRIPTION


def test_the_four_headings_appear_in_order() -> None:
    body = _body()
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_data_file_names_the_decided_chains() -> None:
    assert list(RECIPES) == list(CHAINS)
    for recipe, chain in CHAINS.items():
        assert [step["capability"] for step in RECIPES[recipe]["steps"]] == chain


def test_every_named_capability_resolves_in_the_registry() -> None:
    capabilities = _registry_capabilities()
    body = _body()
    for recipe, chain in CHAINS.items():
        assert recipe in body, recipe
        for capability in chain:
            assert capability in capabilities, f"{capability} is missing from the registry"
            assert capability in body, f"{capability} is missing from the skill"


def test_the_skill_carries_each_handoff_and_verification() -> None:
    body = _body()
    flat = " ".join(body.lower().split())
    for recipe, data in RECIPES.items():
        for step in data["steps"]:
            assert step["capability"] in body
            handoff_token = step["handoff"].split(" ", 1)[0]
            assert handoff_token in body, f"{recipe}: {handoff_token} missing"
            verify = " ".join(step["verify"].rstrip(".").lower().split())
            assert verify in flat, f"{recipe}: {step['verify']} missing"


def test_the_architectural_render_names_the_scripted_capability() -> None:
    """The preset ids are gone from the registry and from the recipes."""
    capabilities = _registry_capabilities()
    for old in ("blender.photo", "blender.product", "blender.tour"):
        assert old not in capabilities, old
    assert "blender.people" not in capabilities
    assert "blender.cars" not in capabilities
    body = _body()
    for old in ("blender.photo", "blender.product", "blender.tour"):
        assert old not in body, old
    assert "blender.scene" in body
    assert "study-photo/study_photo.py" in body


def test_the_skill_names_kokoro_only_as_the_video_alternative() -> None:
    body = _body()
    flat = " ".join(body.lower().split())
    assert "kokoro.speak" in body
    assert "documented voice alternative" in flat
    video = [step["capability"] for step in RECIPES["explainer-video"]["steps"]]
    assert "kokoro.speak" not in video


def test_no_references_dir_ships() -> None:
    assert not (PACKAGE / "skill" / "references").exists()
