"""The comfy manifest: the server pin, the six models and the prompt guard.

The registry suite runs without the core, so the checks here read the
manifest and the flow as data. The closed item set pins what the core turns
into ``invalid_input``: a capability's items are exactly five fields, so a
piece that adds a sixth key is rejected before anything runs. The guard is
the manifest's own ``pattern``, applied the way ``facetmedia.schema`` applies
it (``re.fullmatch``), and the four lab-approved prompts are its regression
test.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "comfy"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
FLOW = json.loads((PACKAGE / "flows" / "z-image-turbo.json").read_text(encoding="utf-8"))
FLOW_KLEIN = json.loads((PACKAGE / "flows" / "flux2-klein-4b.json").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["still"]
IMAGE = CAPABILITY["inputs"]["image"]
ITEMS = IMAGE["items"]
GUARD = re.compile(ITEMS["prompt"]["pattern"])

#: The requirements and image defaults the manifest declares.
RAM_GB = 16
DISK_GB = 25
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 768
SIDE_MIN = 64
SIDE_MAX = 2048
#: The core's skill description bounds.
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200

#: Every whole word the guard must reject: data and lettering in an image.
GUARD_WORDS = (
    "caption",
    "captions",
    "chart",
    "graph",
    "label",
    "labels",
    "letter",
    "letters",
    "logo",
    "sign",
    "text",
    "title",
    "word",
    "words",
)

#: The four prompts of the lab's approved z-image-turbo piece.
LAB_PROMPTS = (
    "Misty pine forest at dawn, soft volumetric light through the trees, muted teal and "
    "amber palette, wide establishing shot, large empty area of fog on the left side, "
    "cinematic, calm",
    "Editorial flat illustration of a woman reading a book under a desk lamp, surrounded "
    "by floating geometric shapes, limited palette of deep blue, coral and cream, subtle "
    "paper grain texture, clean shapes",
    "Studio product photograph of a handmade matte ceramic coffee cup on a raw concrete "
    "surface, soft window light from the left, shallow depth of field, 85mm lens, steam "
    "rising",
    "Loose watercolor painting of a colonial street in a small Andean town, colorful "
    "facades with wooden balconies, cobblestones, green mountains in the background, "
    "visible paper texture and pigment blooms",
)

#: The six models the lab's clone holds, pinned by sha256, size and path.
#: ``flux2-qwen-clip`` shares the z-image clip's file: pull downloads it once.
LAB_MODELS = {
    "z-image-turbo-unet": (
        "be517ebd47c912a5626a588e1aeea43e6be4a43c0cdcd2b48a2a780d9f358635",
        6201001296,
        "z-image-turbo-unet/z_image_turbo_int8_convrot.safetensors",
    ),
    "z-image-qwen-clip": (
        "72450b19758172c5a7273cf7de729d1c17e7f434a104a00167624cba94f68f15",
        5631994051,
        "z-image-qwen-clip/qwen_3_4b_fp8_mixed.safetensors",
    ),
    "z-image-vae": (
        "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
        335304388,
        "z-image-vae/ae.safetensors",
    ),
    "flux2-klein-unet": (
        "ec3d4e733a771f61c052fb4856c48b336c55eaf2c65487c2a1faeb9bbda7a343",
        7751105712,
        "flux2-klein-unet/flux-2-klein-4b.safetensors",
    ),
    "flux2-qwen-clip": (
        "72450b19758172c5a7273cf7de729d1c17e7f434a104a00167624cba94f68f15",
        5631994051,
        "z-image-qwen-clip/qwen_3_4b_fp8_mixed.safetensors",
    ),
    "flux2-klein-vae": (
        "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3",
        336211292,
        "flux2-klein-vae/flux2-vae.safetensors",
    ),
}

#: The Hugging Face repo prefix each model's url must carry.
Z_IMAGE_REPO = (
    "https://huggingface.co/Comfy-Org/Z-Image-Turbo/resolve/"
    "6fc90a3b1b653e935a0d175e260736de25b84df5/"
)
FLUX2_REPO = (
    "https://huggingface.co/Comfy-Org/Flux-2-Klein-4B/resolve/"
    "5b3abca5c0dc1ecd4eaf3340868d09063fc1c965/"
)
MODEL_REPOS = {
    "z-image-turbo-unet": Z_IMAGE_REPO,
    "z-image-qwen-clip": Z_IMAGE_REPO,
    "z-image-vae": Z_IMAGE_REPO,
    "flux2-klein-unet": FLUX2_REPO,
    "flux2-qwen-clip": Z_IMAGE_REPO,
    "flux2-klein-vae": FLUX2_REPO,
}


def test_index_lists_the_comfy_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "comfy" in names


def test_the_package_is_the_image_facet_with_one_still_capability() -> None:
    assert MANIFEST["name"] == "comfy"
    assert MANIFEST["facet"] == "image"
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    assert sorted(MANIFEST["capabilities"]) == ["still"]
    assert CAPABILITY["kind"] == "image"
    assert CAPABILITY["preview"]["viewer"] == "image"


def test_the_server_is_the_pinned_comfyui_launched_on_the_free_port() -> None:
    engine = MANIFEST["engine"]
    assert engine["type"] == "python-env"
    assert engine["python"] == "3.12"
    server = engine["server"]
    assert server["repo"] == "https://github.com/comfyanonymous/ComfyUI.git"
    assert server["rev"] == "3c1b7a17fdf239d35ce98cc777756f572d089795"
    assert server["requirements"] == "requirements.txt"
    assert server["launch"][:2] == ["python", "main.py"]
    assert "--listen" in server["launch"]
    assert any("{{port}}" in token for token in server["launch"])
    assert server["health_url"] == "http://127.0.0.1:{{port}}/system_stats"


def test_the_requirements_are_one_gpu_job() -> None:
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is True
    assert requirements["ram_gb"] == RAM_GB
    assert requirements["disk_gb"] == DISK_GB
    # The core's defaults are exactly this: one heavy job at a time, on linux.
    assert "exclusive" not in requirements
    assert "platforms" not in requirements


def test_the_six_models_are_the_lab_files() -> None:
    models = {model["id"]: model for model in MANIFEST["models"]}
    assert set(models) == set(LAB_MODELS)
    for model_id, (sha256, size, path) in LAB_MODELS.items():
        model = models[model_id]
        assert model["sha256"] == sha256
        assert model["bytes"] == size
        assert model["path"] == path
        assert model["spdx"] == "Apache-2.0"
        assert model["commercial_use"] is True
        assert model["requires_acceptance"] is False
        assert model["url"].startswith(MODEL_REPOS[model_id])
        # Per-file entries: an HF entry would download the whole revision.
        assert "hf_repo" not in model


def test_the_image_input_is_closed_with_five_fields() -> None:
    assert IMAGE["type"] == "array"
    assert IMAGE["required"] is True
    assert IMAGE["min_items"] == 1
    assert set(ITEMS) == {"name", "prompt", "seed", "width", "height"}
    assert ITEMS["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert ITEMS["seed"]["required"] is True
    assert ITEMS["seed"]["type"] == "integer"
    assert ITEMS["width"]["default"] == DEFAULT_WIDTH
    assert ITEMS["height"]["default"] == DEFAULT_HEIGHT
    for side in ("width", "height"):
        assert ITEMS[side]["min"] == SIDE_MIN
        assert ITEMS[side]["max"] == SIDE_MAX


def test_the_workflow_input_is_an_enum_with_a_default() -> None:
    workflow = CAPABILITY["inputs"]["workflow"]
    assert workflow["type"] == "enum"
    assert workflow["values"] == ["z-image-turbo", "flux2-klein-4b"]
    assert workflow["default"] == "z-image-turbo"
    assert workflow["default"] in workflow["values"]


@pytest.mark.parametrize("word", GUARD_WORDS)
def test_the_guard_rejects_every_data_word(word: str) -> None:
    assert GUARD.fullmatch(f"A quiet {word} in the scene") is None
    assert GUARD.fullmatch(word.upper()) is None


def test_the_guard_rejects_a_data_word_in_caps() -> None:
    assert GUARD.fullmatch("A CHART") is None


@pytest.mark.parametrize("prompt", LAB_PROMPTS)
def test_the_guard_accepts_the_four_lab_prompts(prompt: str) -> None:
    assert GUARD.fullmatch(prompt) is not None


def test_the_guard_keeps_texture_digits_and_longer_words() -> None:
    assert GUARD.fullmatch("subtle paper grain texture, 85mm lens") is not None
    # "photograph" holds "graph" and "design" holds "sign": whole words only.
    assert GUARD.fullmatch("a photograph of a design") is not None


def test_the_flow_fills_the_names_of_the_three_models() -> None:
    graph = FLOW["graph"]
    assert graph["unet"]["inputs"]["unet_name"] == Path(LAB_MODELS["z-image-turbo-unet"][2]).name
    assert graph["clip"]["inputs"]["clip_name"] == Path(LAB_MODELS["z-image-qwen-clip"][2]).name
    assert graph["vae"]["inputs"]["vae_name"] == Path(LAB_MODELS["z-image-vae"][2]).name
    assert FLOW["params"] == {"width": 1344, "height": 768, "seed": 0, "steps": 8, "shift": 3}
    placeholders = set(re.findall(r'"\$([a-z]+)"', json.dumps(graph)))
    assert placeholders == {"prompt", "seed", "width", "height", "steps", "shift", "name"}


def test_the_klein_flow_fills_the_names_of_its_three_models() -> None:
    graph = FLOW_KLEIN["graph"]
    assert graph["unet"]["inputs"]["unet_name"] == Path(LAB_MODELS["flux2-klein-unet"][2]).name
    assert graph["clip"]["inputs"]["clip_name"] == Path(LAB_MODELS["flux2-qwen-clip"][2]).name
    assert graph["vae"]["inputs"]["vae_name"] == Path(LAB_MODELS["flux2-klein-vae"][2]).name
    assert FLOW_KLEIN["params"] == {"width": 1344, "height": 768, "seed": 0, "steps": 4}
    placeholders = set(re.findall(r'"\$([a-z]+)"', json.dumps(graph)))
    assert placeholders == {"prompt", "seed", "width", "height", "steps", "name"}


def test_the_skill_is_valid_and_names_the_capability() -> None:
    text = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
    lines = text.split("\n")
    assert lines[0] == "---"
    end = lines.index("---", 1)
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, _separator, value = line.partition(":")
        meta[key.strip()] = value.strip()
    assert meta["name"] == "comfy"
    assert DESCRIPTION_MIN <= len(meta["description"]) <= DESCRIPTION_MAX
    headings = [
        line.removeprefix("## ").strip() for line in lines[end + 1 :] if line.startswith("## ")
    ]
    required = ["When to use", "Pieces", "Judging the result", "Pitfalls"]
    assert [heading for heading in headings if heading in required] == required
    assert "comfy.still" in text
