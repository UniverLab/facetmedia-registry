"""The voicestudio manifest: the transitional no-server pin, the voice, and the

verification loop's manifest side. The registry suite runs without the core,
so the checks here read the manifest as data: the engine must stay serverless
(managed provisioning is the core follow-up, and a `[engine.server]` table
would make facet try to build the backend it cannot build), the piece format
must carry exactly one piece-level model and no entry key for it (the mixed
engine is unrepresentable), and every entry needs a seed, because the runner
regenerates a failing clip with `seed + 1`. The skill file must validate in
the core's format, because the registry rejects packages without one.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "voicestudio"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["speak"]
INPUTS = CAPABILITY["inputs"]
CLIP = INPUTS["clip"]
CLIP_ITEMS = CLIP["items"]
NAME_PATTERN = re.compile(CLIP_ITEMS["name"]["pattern"])
READ = (PACKAGE / "README.md").read_text(encoding="utf-8")
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
#: The core's skill description bounds.
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
#: The verification model the manifest pins, byte for byte.
REVISION = "536b0662742c02347bc0e980a01041f333bce120"
WHISPER_BYTES = 486_212_372
#: The requirements the manifest declares.
RAM_GB = 8
DISK_GB = 2


def test_the_engine_is_python_312_with_no_server_table() -> None:
    assert MANIFEST["name"] == "voicestudio"
    assert MANIFEST["facet"] == "voice"
    assert MANIFEST["version"] == "0.1.0"
    assert MANIFEST["engine"]["type"] == "python-env"
    assert MANIFEST["engine"]["python"] == "3.12"
    assert "server" not in MANIFEST["engine"]
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}


def test_the_runner_is_a_client_of_two_lib_modules() -> None:
    assert MANIFEST["uses"] == ["textnorm", "audiopreview"]
    for name in MANIFEST["uses"]:
        assert (ROOT / "lib" / f"{name}.py").is_file()


def test_the_piece_voice_is_the_narradora_clone() -> None:
    voice = INPUTS["voice"]
    assert voice["values"] == ["narradora"]
    assert voice["default"] == "narradora"


def test_the_piece_engine_is_voxcpm2_alone() -> None:
    model = INPUTS["model"]
    assert model["values"] == ["voxcpm2"]
    assert model["default"] == "voxcpm2"
    language = INPUTS["language"]
    assert language["values"] == ["es"]
    assert language["default"] == "es"


def test_the_entries_carry_exactly_name_text_seed() -> None:
    """The closed item set: no per-entry model, voice or skip key exists."""
    assert CLIP["required"] is True
    assert set(CLIP_ITEMS) == {"name", "text", "seed"}
    assert CLIP_ITEMS["name"]["required"] is True
    assert CLIP_ITEMS["text"]["required"] is True
    assert CLIP_ITEMS["seed"]["type"] == "integer"
    assert CLIP_ITEMS["seed"]["required"] is True


def test_the_entry_names_match_the_pattern() -> None:
    assert NAME_PATTERN.fullmatch("intro")
    assert NAME_PATTERN.fullmatch("a-narracion")
    assert NAME_PATTERN.fullmatch("Intro") is None
    assert NAME_PATTERN.fullmatch("a b") is None


def test_no_skip_field_can_reach_the_runner() -> None:
    """Verification is always on: the format has nothing to switch it off."""
    assert "skip" not in INPUTS
    assert "skip" not in CLIP_ITEMS
    assert "no-verify" not in INPUTS
    assert "no-verify" not in CLIP_ITEMS


def test_the_result_is_judged_and_previewed_as_audio() -> None:
    assert CAPABILITY["kind"] == "audio"
    assert CAPABILITY["verify"]["thresholds"] == {"wer_max": 0.05}
    assert CAPABILITY["preview"] == {"viewer": "audio"}


def test_the_piece_needs_the_machine_the_engine_wants() -> None:
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is True
    assert requirements["ram_gb"] == RAM_GB
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is True
    assert requirements["platforms"] == ["linux"]


def test_the_verification_model_is_pinned() -> None:
    assert len(MANIFEST["models"]) == 1
    model = MANIFEST["models"][0]
    assert model["id"] == "faster-whisper-small-verify"
    assert model["hf_repo"] == "Systran/faster-whisper-small"
    assert model["revision"] == REVISION
    assert model["bytes"] == WHISPER_BYTES
    assert model["spdx"] == "MIT"
    assert model["commercial_use"] is True
    assert model["requires_acceptance"] is False
    assert model["terms_url"] == "https://huggingface.co/Systran/faster-whisper-small"
    assert re.fullmatch(r"[0-9a-f]{40}", model["revision"])


def test_the_model_id_is_unique_across_the_registry() -> None:
    """kokoro already declares the bare whisper name, so ids may not repeat."""
    ids: list[str] = []
    for package in sorted((ROOT / "packages").iterdir()):
        manifest = package / "package.toml"
        if manifest.is_file():
            parsed = tomllib.loads(manifest.read_text(encoding="utf-8"))
            ids.extend(str(entry["id"]) for entry in parsed.get("models", []))
    assert "faster-whisper-small-verify" in ids
    assert len(ids) == len(set(ids)), "model ids must not repeat across packages"


def test_the_licences_name_the_backend_and_the_verifier() -> None:
    licences = {(entry["subject"], entry["spdx"]) for entry in MANIFEST["licenses"]}
    assert ("VoiceStudio (the backend this package talks to)", "AGPL-3.0-only") in licences
    assert ("faster-whisper", "MIT") in licences
    assert ("ctranslate2", "MIT") in licences


def test_the_skill_validates_in_the_core_format() -> None:
    first, second, *rest = SKILL.split("---", 2)
    assert first == "" and second.strip().startswith("name:")
    frontmatter = second.strip().splitlines()
    assert {"name: voicestudio"} <= set(frontmatter)
    assert next(line for line in frontmatter if line.startswith("description:")).startswith(
        "description:"
    )
    description = next(
        line.removeprefix("description:").strip()
        for line in frontmatter
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX
    body = rest[0]
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions), "the four headings must appear in order"


def test_the_index_lists_the_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert names == ["ascii", "cad", "comfy", "ffmpeg", "kokoro", "whisper", "voicestudio"]


def test_the_readme_carries_the_user_start_recipe() -> None:
    assert "uvicorn main:app --app-dir backend" in READ
    assert "wer_max = 0.05" not in READ  # the threshold lives in the manifest
    assert "REGENERATE" in READ
    assert "VOICESTUDIO_URL" in READ


@pytest.mark.parametrize(
    ("input_name", "present"),
    [("voice", True), ("model", True), ("language", True), ("clip", True), ("speed", False)],
)
def test_the_piece_inputs_are_exactly_the_four(input_name: str, present: bool) -> None:
    assert (input_name in INPUTS) is present
