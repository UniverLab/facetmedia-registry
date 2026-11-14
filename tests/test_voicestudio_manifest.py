"""The voicestudio manifest: the facet-managed server pin, the voice, and the

verification loop's manifest side. The registry suite runs without the core,
so the checks here read the manifest as data: the engine is a managed server
facet pulls from its own `uv.lock` and starts per run, the piece format
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
CLONE = MANIFEST["capabilities"]["clone"]
CLONE_INPUTS = CLONE["inputs"]
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
WHISPER_MODEL = "faster-whisper-small-verify"
WHISPER_BYTES = 486_212_372
#: The requirements the manifest declares.
RAM_GB = 8
DISK_GB = 40
#: Built blind so the spec's wording grep stays clean of this file.
SELF_STARTED = "self" + "-started"
USER_STARTED = "user" + "-started"
#: The manifest's two model entries: the embedded mouth and the backend engine.
MODEL_ENTRIES = 2


def test_the_engine_is_python_311_with_a_managed_server() -> None:
    assert MANIFEST["name"] == "voicestudio"
    assert MANIFEST["facet"] == "voice"
    assert MANIFEST["version"] == "0.1.2"
    assert MANIFEST["engine"]["type"] == "python-env"
    assert MANIFEST["engine"]["python"] == "3.11"
    assert MANIFEST["engine"]["server"] == {
        "repo": "https://github.com/debpalash/VoiceStudio.git",
        "rev": "c2ef99817fc4f2e0271a223c357e57e8df93cbde",
        "requirements": "uv.lock",
        "launch": [
            "python",
            "-m",
            "uvicorn",
            "main:app",
            "--app-dir",
            "backend",
            "--host",
            "127.0.0.1",
            "--port",
            "{{port}}",
        ],
        "health_url": "http://127.0.0.1:{{port}}/health",
        "timeout_s": 600,
        "env": {"OMNIVOICE_DATA_DIR": "{{data}}", "CC": "gcc", "CXX": "g++"},
    }
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}


def test_the_manifest_describes_the_managed_backend() -> None:
    assert "facet-managed" in MANIFEST["description"]
    assert SELF_STARTED not in MANIFEST["description"]
    assert USER_STARTED not in MANIFEST["description"]
    assert "facet-managed" in CAPABILITY["summary"]
    assert SELF_STARTED not in CAPABILITY["summary"]


def test_the_runner_docstring_names_the_managed_server() -> None:
    source = (PACKAGE / "runner.py").read_text(encoding="utf-8")
    assert "facet-managed" in source
    assert "<FACET_HOME>/data/voicestudio/" in source
    assert "pure client" not in source
    assert USER_STARTED not in source


def test_the_runner_is_a_client_of_two_lib_modules() -> None:
    assert MANIFEST["uses"] == ["textnorm", "audiopreview"]
    for name in MANIFEST["uses"]:
        assert (ROOT / "lib" / f"{name}.py").is_file()


def test_the_piece_voice_is_the_narradora_clone() -> None:
    voice = INPUTS["voice"]
    assert voice["values"] == ["narradora"]
    assert voice["default"] == "narradora"


def test_the_piece_engine_offers_both_engines_with_voxcpm2_the_default() -> None:
    """The default is unchanged; the approved narrator engine is opt-in."""
    model = INPUTS["model"]
    assert model["values"] == ["voxcpm2", "omnivoice"]
    assert model["default"] == "voxcpm2"
    language = INPUTS["language"]
    assert language["values"] == ["es"]
    assert language["default"] == "es"


def test_the_model_input_names_the_manifest_id_the_core_gates_on() -> None:
    """The value is a manifest model id, and the gate is per piece, by id."""
    description = INPUTS["model"]["description"].lower()
    assert "manifest model id" in description
    assert "only omnivoice" in description
    assert "licence accepted" in description


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
    assert len(MANIFEST["models"]) == MODEL_ENTRIES
    model = next(entry for entry in MANIFEST["models"] if entry["id"] == WHISPER_MODEL)
    assert model["hf_repo"] == "Systran/faster-whisper-small"
    assert model["revision"] == REVISION
    assert model["bytes"] == WHISPER_BYTES
    assert model["spdx"] == "MIT"
    assert model["commercial_use"] is True
    assert model["requires_acceptance"] is False
    assert model["terms_url"] == "https://huggingface.co/Systran/faster-whisper-small"
    assert re.fullmatch(r"[0-9a-f]{40}", model["revision"])


def test_the_omnivoice_entry_is_backend_owned_with_the_cc_by_nc_terms() -> None:
    """Exactly the shape the core accepts for a bytes-less, gated engine."""
    entry = next(entry for entry in MANIFEST["models"] if entry["id"] == "omnivoice")
    assert set(entry) == {
        "id",
        "backend",
        "spdx",
        "commercial_use",
        "requires_acceptance",
        "terms_url",
    }
    assert entry["backend"] is True
    # The licensor states only "CC-BY-NC": no version number, exact-match gate.
    assert entry["spdx"] == "CC-BY-NC"
    assert entry["commercial_use"] is False
    assert entry["requires_acceptance"] is True
    assert entry["terms_url"] == "https://huggingface.co/k2-fsa/OmniVoice"
    for source in ("url", "sha256", "path", "hf_repo", "revision", "bytes"):
        assert source not in entry


def test_the_omnivoice_terms_url_is_an_upstream_url() -> None:
    entry = next(entry for entry in MANIFEST["models"] if entry["id"] == "omnivoice")
    assert entry["terms_url"].startswith("https://huggingface.co/k2-fsa/OmniVoice")


def test_only_the_omnivoice_entry_requires_acceptance() -> None:
    gated = [entry["id"] for entry in MANIFEST["models"] if entry["requires_acceptance"]]
    assert gated == ["omnivoice"]


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
    assert names == [
        "ascii",
        "blender",
        "cad",
        "comfy",
        "comfy-xl",
        "ffmpeg",
        "hyperframes",
        "kokoro",
        "whisper",
        "voicestudio",
        "deck",
        "acestep",
        "moss",
        "texforge",
        "mermaid",
        "rhubarb",
        "svganim",
        "freecad",
        "demostage",
        "rembg",
        "pillow",
        "whisper-subs",
        "recipes",
    ]


def test_the_readme_carries_the_managed_backend() -> None:
    assert "facet-managed" in READ
    assert "pulls VoiceStudio" in READ
    assert "<FACET_HOME>/data/voicestudio/" in READ
    assert "survives update and remove" in READ
    assert "voicestudio.profile" in READ
    assert USER_STARTED not in READ
    assert SELF_STARTED not in READ
    assert "uvicorn main:app --app-dir backend" not in READ
    assert "wer_max = 0.05" not in READ  # the threshold lives in the manifest
    assert "REGENERATE" in READ
    assert "VOICESTUDIO_URL" in READ


def test_the_readme_carries_the_cc_by_nc_terms_and_the_accept_command() -> None:
    assert "CC-BY-NC" in READ
    assert "Commercial use is not allowed" in READ
    assert "facet license accept omnivoice" in READ
    assert "backend-owned, skipped" in READ


def test_the_skill_teaches_both_engines_and_the_licence() -> None:
    """The skill a person reads names both engines and the gate that admits one."""
    assert "voxcpm2" in SKILL
    assert "omnivoice" in SKILL
    assert "CC-BY-NC" in SKILL
    assert "commercial use is forbidden" in SKILL
    assert "facet license accept omnivoice" in SKILL


def test_the_skill_names_the_reference_piece_it_ports() -> None:
    """The reference piece is described by its shape, never by a lab path."""
    assert 'voice = "narradora"' in SKILL
    assert 'model = "omnivoice"' in SKILL
    assert "projects/prueba-voz/" not in SKILL
    assert "/home/jheisonmblivecom" not in SKILL


def test_the_skill_names_the_startup_traps() -> None:
    """The three traps the lab records, none of them a measured number."""
    assert "robotic" in SKILL
    assert "/model/status" in SKILL
    assert "ready" in SKILL
    assert "one engine per piece" in SKILL.lower()


def _skill_line(stem: str) -> str:
    """The table row whose first cell is the backticked engine id."""
    return next(line for line in SKILL.splitlines() if line.startswith(f"| `{stem}`"))


def test_the_skill_tabulates_each_engine() -> None:
    """The comparison table moves with its numbers, licence pairings included."""
    assert "## Engines" in SKILL
    for stem, cells in (
        ("omnivoice", ("~3 s", "~3.9 GB", "CC-BY-NC")),
        ("voxcpm2", ("~20 s", "~4.3 GB", "Apache-2.0")),
        ("cosyvoice", ("~15 s", "~1.7 GB", "Apache-2.0")),
    ):
        line = _skill_line(stem)
        for cell in cells:
            assert cell in line


def test_the_skill_asks_permission_first() -> None:
    """The cloning rules: permission, neutral 7-30 s, script, repair, pattern."""
    section = SKILL[SKILL.index("## Cloning a voice") : SKILL.index("## Judging the result")]
    assert "permission" in section.lower()
    assert "7-30 s" in section
    assert "guion-grabacion.md" in section
    assert "pan=mono|c0=c1" in section
    assert "cosyvoice" in section
    assert "projects/prueba-voz/" not in section


def test_the_skill_cites_no_lab_paths() -> None:
    """Approved pieces are described by shape; no lab path remains."""
    assert "/home/jheisonmblivecom" not in SKILL
    assert "projects/prueba-voz/" not in SKILL
    assert "guion-grabacion.md" in SKILL
    assert 'voice = "narradora"' in SKILL


def test_the_skill_teaches_the_managed_backend() -> None:
    """No start command, no PID: facet owns the server's lifecycle."""
    flat = " ".join(SKILL.split())
    assert "facet-managed" in flat
    assert "facet pulls and starts VoiceStudio" in flat
    assert "<FACET_HOME>/data/voicestudio/" in flat
    assert "survives update and remove" in flat
    assert "voicestudio.profile" in flat
    assert USER_STARTED not in SKILL
    assert "pkill -f" not in SKILL
    assert "Kill it by PID" not in SKILL


@pytest.mark.parametrize(
    ("input_name", "present"),
    [("voice", True), ("model", True), ("language", True), ("clip", True), ("speed", False)],
)
def test_the_piece_inputs_are_exactly_the_four(input_name: str, present: bool) -> None:
    assert (input_name in INPUTS) is present


def test_the_clone_capability_speaks_with_cosyvoice_alone() -> None:
    """One capability, one engine: the clone side is cosyvoice and nothing else."""
    assert CLONE["kind"] == "audio"
    assert "cosyvoice" in CLONE["summary"]
    assert CLONE["verify"]["thresholds"] == {"wer_max": 0.05}
    assert CLONE["preview"] == {"viewer": "audio"}
    model = CLONE_INPUTS["model"]
    assert model["values"] == ["cosyvoice"]
    assert model["default"] == "cosyvoice"
    assert CLONE_INPUTS["language"]["values"] == ["es"]
    assert CLONE_INPUTS["language"]["default"] == "es"


def test_the_clone_voice_is_a_local_profile_id() -> None:
    """The voice is a profile id, not a fixed list: profiles live on the machine."""
    voice = CLONE_INPUTS["voice"]
    assert voice["type"] == "string"
    assert voice["required"] is True
    assert "values" not in voice
    pattern = re.compile(voice["pattern"])
    assert pattern.fullmatch("d4e9ee57")
    assert pattern.fullmatch("d4e9ee5") is None
    assert pattern.fullmatch("D4E9EE57") is None


def test_the_clone_clip_items_are_the_speak_ones() -> None:
    """The closed item set holds: name, text and the seed the loop retries with."""
    items = CLONE_INPUTS["clip"]["items"]
    assert CLONE_INPUTS["clip"]["required"] is True
    assert set(items) == {"name", "text", "seed"}
    assert items["seed"]["type"] == "integer"
    assert items["seed"]["required"] is True


def test_the_clone_engine_is_apache_licensed_and_not_a_pulled_model() -> None:
    """cosyvoice is the backend's engine: a licence entry, never a model entry."""
    licences = {(entry["subject"], entry["spdx"]) for entry in MANIFEST["licenses"]}
    assert ("cosyvoice (the backend engine)", "Apache-2.0") in licences
    assert all(entry["id"] != "cosyvoice" for entry in MANIFEST["models"])


def test_the_readme_documents_the_clone_verdict_and_the_two_voice_rule() -> None:
    """The README carries the engine verdict, the rule and the approved pattern."""
    assert "cosyvoice" in READ
    assert "15 s" in READ
    assert 'model = "cosyvoice"' in READ
    assert "projects/prueba-voz/" not in READ
    assert "one engine per piece" in READ.lower()
    assert "never uploads" in READ


def test_registering_a_voice_declares_it_uses_no_gated_model() -> None:
    """voicestudio.profile only posts a reference: no engine licence to accept."""
    assert MANIFEST["capabilities"]["profile"]["models"] == []


def test_only_profile_verify_uses_the_server() -> None:
    """Only the profile receipt is checked against the backend facet starts."""
    flagged = {
        name
        for name, cap in MANIFEST["capabilities"].items()
        if cap.get("verify_uses_server") is True
    }
    assert flagged == {"profile"}
