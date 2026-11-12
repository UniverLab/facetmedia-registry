"""The acestep manifest: the server pin, the backend-owned models and the bed.

The registry suite runs without the core, so these checks read the manifest as
data: the ``[engine.server]`` a facet starts, the two checkpoints the server
fetches, and the closed set of inputs facet validates a piece against. The
approved allegro piece is the regression test that the input names and the
``duration`` bound are real.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "acestep"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
BED = MANIFEST["capabilities"]["bed"]
INPUTS = BED["inputs"]
EXAMPLE = PACKAGE / "examples" / "clasica-alegre.toml"

#: The requirements and the cap the manifest declares.
RAM_GB = 16
DISK_GB = 24
MAX_DURATION = 30
DURATION_TOLERANCE_S = 1.0
PEAK_DBFS_MIN = -40.0
SERVER_TIMEOUT_S = 600
#: A full git revision, forty lowercase hex digits.
REV_RE = re.compile(r"[0-9a-f]{40}\Z")
#: The bed defaults the runner sends when a piece leaves them unset.
DEFAULT_SEED = 0
DEFAULT_STEPS = 8
DEFAULT_GUIDANCE = 7.0
#: The tempo bounds a bed accepts.
MIN_BPM = 30
MAX_BPM = 300


def test_index_lists_the_acestep_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "acestep" in names


def test_the_package_is_the_audio_facet_with_one_bed() -> None:
    assert MANIFEST["name"] == "acestep"
    assert MANIFEST["facet"] == "audio"
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    assert MANIFEST["uses"] == ["audiopreview"]
    assert sorted(MANIFEST["capabilities"]) == ["bed"]
    assert BED["kind"] == "audio"
    assert BED["preview"]["viewer"] == "audio"


def test_the_server_is_the_pinned_acestep_api_launched_on_the_free_port() -> None:
    engine = MANIFEST["engine"]
    assert engine["type"] == "python-env"
    assert engine["python"] == "3.12"
    server = engine["server"]
    assert server["repo"] == "https://github.com/ace-step/ACE-Step-1.5.git"
    assert REV_RE.fullmatch(server["rev"])
    assert server["requirements"] == "uv.lock"
    # The launcher the clone's own run_api_server.sh documents.
    assert server["launch"][:3] == ["python", "-m", "uvicorn"]
    assert "acestep.api_server:app" in server["launch"]
    assert "--workers" in server["launch"]
    assert any("{{port}}" in token for token in server["launch"])
    assert server["health_url"] == "http://127.0.0.1:{{port}}/health"
    assert server["timeout_s"] == SERVER_TIMEOUT_S


def test_the_requirements_are_one_gpu_job() -> None:
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is True
    assert requirements["ram_gb"] == RAM_GB
    assert requirements["disk_gb"] == DISK_GB
    assert requirements["exclusive"] is True
    assert requirements["platforms"] == ["linux"]


def test_the_two_models_are_backend_owned_and_mit() -> None:
    models = {model["id"]: model for model in MANIFEST["models"]}
    assert set(models) == {"acestep-v15-turbo", "acestep-vae"}
    for model in models.values():
        assert model["backend"] is True
        assert model["spdx"] == "MIT"
        assert model["commercial_use"] is True
        assert model["requires_acceptance"] is False
        # Backend-owned: the core rejects any source key on these entries.
        for key in ("url", "sha256", "path", "hf_repo", "revision", "bytes"):
            assert key not in model, key


def test_the_bed_inputs_are_caption_name_and_duration() -> None:
    assert set(INPUTS) == {
        "caption",
        "name",
        "duration",
        "seed",
        "steps",
        "guidance",
        "bpm",
        "key",
        "time-signature",
    }
    assert INPUTS["caption"]["type"] == "string"
    assert INPUTS["caption"]["required"] is True
    assert INPUTS["name"]["type"] == "string"
    assert INPUTS["name"]["required"] is True
    assert INPUTS["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert INPUTS["duration"]["type"] == "number"
    assert INPUTS["duration"]["required"] is True
    assert INPUTS["duration"]["max"] == MAX_DURATION
    assert INPUTS["seed"]["type"] == "integer"
    assert INPUTS["seed"]["default"] == DEFAULT_SEED
    assert INPUTS["seed"]["min"] == DEFAULT_SEED
    assert INPUTS["steps"]["type"] == "integer"
    assert INPUTS["steps"]["default"] == DEFAULT_STEPS
    assert INPUTS["steps"]["min"] == 1
    assert INPUTS["guidance"]["type"] == "number"
    assert INPUTS["guidance"]["default"] == DEFAULT_GUIDANCE
    assert INPUTS["guidance"]["min"] == 0
    assert INPUTS["bpm"]["type"] == "integer"
    assert INPUTS["bpm"]["required"] is False
    assert INPUTS["bpm"]["min"] == MIN_BPM
    assert INPUTS["bpm"]["max"] == MAX_BPM
    assert "default" not in INPUTS["bpm"]
    assert INPUTS["key"]["type"] == "string"
    assert INPUTS["key"]["required"] is False
    assert "default" not in INPUTS["key"]
    assert INPUTS["time-signature"]["type"] == "string"
    assert INPUTS["time-signature"]["required"] is False
    assert "default" not in INPUTS["time-signature"]


def test_the_bed_verifies_duration_and_peak() -> None:
    assert BED["verify"]["thresholds"] == {
        "duration_tolerance_s": DURATION_TOLERANCE_S,
        "peak_dbfs_min": PEAK_DBFS_MIN,
    }


def test_the_example_piece_is_runnable() -> None:
    data = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    inputs = data["inputs"]
    assert set(inputs) <= set(INPUTS)
    assert set(inputs) == {"caption", "name", "duration"}
    assert re.fullmatch(INPUTS["name"]["pattern"], inputs["name"])
    assert inputs["duration"] == MAX_DURATION
    assert "No drums, no percussion, no bass beat, no synthesizers" in inputs["caption"]
