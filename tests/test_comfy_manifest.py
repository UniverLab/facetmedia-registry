"""The comfy manifest: the server pin, the ten models and the prompt guard.

The registry suite runs without the core, so the checks here read the
manifest and the flow as data. The closed item set pins what the core turns
into ``invalid_input``: each capability's items are pinned exactly, so a
piece that adds a key the manifest does not declare is rejected before
anything runs. The guard is
the manifest's own ``pattern``, applied the way ``facetmedia.schema`` applies
it (``re.fullmatch``), and the four lab-approved prompts are its regression
test.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "comfy"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
FLOW = json.loads((PACKAGE / "flows" / "z-image-turbo.json").read_text(encoding="utf-8"))
FLOW_KLEIN = json.loads((PACKAGE / "flows" / "flux2-klein-4b.json").read_text(encoding="utf-8"))
FLOW_IMG2IMG = json.loads(
    (PACKAGE / "flows" / "flux2-klein-img2img.json").read_text(encoding="utf-8")
)
FLOW_WAN = json.loads((PACKAGE / "flows" / "wan22-i2v.json").read_text(encoding="utf-8"))
CAPABILITY = MANIFEST["capabilities"]["still"]
EDIT = MANIFEST["capabilities"]["edit"]
CLIP = MANIFEST["capabilities"]["clip"]
IMAGE = CAPABILITY["inputs"]["image"]
ITEMS = IMAGE["items"]
EDIT_ITEMS = EDIT["inputs"]["image"]["items"]
EDIT_SOURCE = EDIT["inputs"]["source"]
CLIP_ITEMS = CLIP["inputs"]["image"]["items"]
GUARD = re.compile(ITEMS["prompt"]["pattern"])

#: The requirements and image defaults the manifest declares.
RAM_GB = 16
DISK_GB = 40
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 768
DEFAULT_CLIP_WIDTH = 1280
DEFAULT_CLIP_HEIGHT = 704
DEFAULT_CLIP_LENGTH = 49
KLEIN_STEPS = 4
CFG = 1
KLEIN_CFG = 1
SIDE_MIN = 64
SIDE_MAX = 2048
STEPS_MIN = 1
CFG_MIN = 0
SHIFT_MIN = 0
#: The core's skill description bounds.
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200

#: The sampling knobs an entry may set: manifest type and minimum, if any.
KNOB_FIELDS = {
    "steps": ("integer", STEPS_MIN),
    "cfg": ("number", CFG_MIN),
    "sampler": ("string", None),
    "scheduler": ("string", None),
    "shift": ("number", SHIFT_MIN),
}
#: A graph input's name to the placeholder and params key that fills it.
KNOB_INPUTS = {
    "steps": "steps",
    "cfg": "cfg",
    "sampler_name": "sampler",
    "scheduler": "scheduler",
    "shift": "shift",
}
#: Every flow's sampling knobs: the default each placeholder falls back to.
FLOW_KNOBS = {
    "z-image-turbo": {
        "steps": 8,
        "cfg": 1,
        "sampler": "res_multistep",
        "scheduler": "simple",
        "shift": 3,
    },
    "flux2-klein-4b": {"steps": 4, "cfg": 1, "sampler": "euler"},
    "flux2-klein-img2img": {"steps": 4, "cfg": 1, "sampler": "euler"},
    "wan22-i2v": {
        "steps": 20,
        "cfg": 5,
        "sampler": "uni_pc",
        "scheduler": "simple",
        "shift": 8,
    },
    "wan22-i2v-fast": {
        "steps": 4,
        "cfg": 1,
        "sampler": "euler",
        "scheduler": "simple",
        "shift": 8,
    },
}

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

#: The prompt of the lab's approved img2img piece.
LAB_EDIT_PROMPT = (
    "Edit the reference image into a two-color linocut print in deep indigo and warm cream. "
    "Preserve the woman reading under the desk lamp, the framing, and the large geometric "
    "shapes. Use rough carved edges and visible paper grain. Do not add lettering or symbols."
)

#: The prompts of the lab's approved clip piece: movement inside the frame.
LAB_CLIP_PROMPTS = (
    "Fog drifting slowly between the pine trees at dawn, soft light rays shifting through "
    "the mist, very slow camera push in, calm and quiet, cinematic",
    "Steam rising and curling gently from the ceramic coffee cup, soft window light, static "
    "camera, shallow depth of field, calm product shot",
    "Slow camera pan to the right along the colonial street, clouds drifting over the green "
    "mountains, watercolor painting style preserved, gentle movement",
)

#: The lab's engraved-plate clip: the motion first, then the engraving style,
#: with the custom negative that keeps invented hands and new objects out.
PLATE_PROMPT = (
    "The large spoked flywheel of the antique printing press spins clockwise continuously, "
    "making several full turns, its spokes clearly rotating; the foot treadle pumps up and "
    "down again and again; the round ink disc on top keeps turning. Constant steady "
    "mechanical motion through the whole clip. The image stays a 19th-century copperplate "
    "engraving: fine black ink hatching on flat cream paper, identical drawing style in "
    "every frame. Static camera, nothing else changes."
)
PLATE_NEGATIVE = (
    "static, still image, frozen, motionless, no movement, 3D render, CGI, photorealistic, "
    "metallic reflections, glossy metal, smooth shading, gradients, color change, "
    "oversaturated, camera movement, zoom, blur, text, subtitles, paper sheet, new objects, "
    "deformed machine, melting, morphing"
)

#: The ten models the lab's clone holds, pinned by sha256, size and path.
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
    "wan2v2-unet": (
        "a83f54a2450d5471e5721e59ab556afa2d8793e30280713e3796b254c5286b48",
        5277255650,
        "wan2v2-unet/Wan2_2-TI2V-5B_fp8_e4m3fn_scaled_KJ.safetensors",
    ),
    "wan2v2-vae": (
        "e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156",
        1409400960,
        "wan2v2-vae/wan2.2_vae.safetensors",
    ),
    "wan2v2-clip": (
        "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
        6735906897,
        "wan2v2-clip/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    ),
    "wan2v2-fastwan-lora": (
        "79290493711b022e1c6e655d803715cd8a91a75cdb139856cad46f354e2f681c",
        660874456,
        "wan2v2-fastwan-lora/Wan2_2_5B_FastWanFullAttn_lora_rank_128_bf16.safetensors",
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
WAN_REPO = (
    "https://huggingface.co/Comfy-Org/Wan-2.2/resolve/ee6f4a40737a995bf5818954cfce6d59443b0f04/"
)
KIJAI_REPO = (
    "https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled/resolve/"
    "033a4e487f60220b3d6e469599a6aebc46e13cee/"
)
FASTWAN_REPO = (
    "https://huggingface.co/Kijai/WanVideo_comfy/resolve/8260d429d19fd7a72304cad059160b95d843913f/"
)
MODEL_REPOS = {
    "z-image-turbo-unet": Z_IMAGE_REPO,
    "z-image-qwen-clip": Z_IMAGE_REPO,
    "z-image-vae": Z_IMAGE_REPO,
    "flux2-klein-unet": FLUX2_REPO,
    "flux2-qwen-clip": Z_IMAGE_REPO,
    "flux2-klein-vae": FLUX2_REPO,
    "wan2v2-unet": KIJAI_REPO,
    "wan2v2-vae": WAN_REPO,
    "wan2v2-clip": WAN_REPO,
    "wan2v2-fastwan-lora": FASTWAN_REPO,
}


def test_index_lists_the_comfy_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "comfy" in names


def test_the_package_declares_the_shared_comfy_client() -> None:
    assert MANIFEST["uses"] == ["comfyclient"]
    assert (ROOT / "lib" / "comfyclient.py").is_file()


def test_the_package_is_the_image_facet_with_still_edit_and_clip() -> None:
    assert MANIFEST["name"] == "comfy"
    assert MANIFEST["facet"] == "image"
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    assert sorted(MANIFEST["capabilities"]) == ["clip", "edit", "still"]
    assert CAPABILITY["kind"] == "image"
    assert CAPABILITY["preview"]["viewer"] == "image"
    assert CLIP["kind"] == "video"
    assert CLIP["preview"]["viewer"] == "video"


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
    # Without it the Wan flow peaked at 18 of 19 GB of RAM.
    assert "--disable-pinned-memory" in server["launch"]
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


def test_the_ten_models_are_the_lab_files() -> None:
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


def _assert_knob_fields(items: dict[str, dict[str, object]], names: tuple[str, ...]) -> None:
    """Each knob is optional, typed as declared, and defaults to the flow's value."""
    for name in names:
        field = items[name]
        kind, low = KNOB_FIELDS[name]
        assert field["type"] == kind, name
        assert field["required"] is False, name
        # The default lives in the flow's params, never in the manifest.
        assert "default" not in field, name
        assert "flow default" in field["description"], name
        if low is None:
            assert "min" not in field, name
        else:
            assert field["min"] == low, name


def test_the_image_input_is_closed_with_its_sizes_and_knobs() -> None:
    assert IMAGE["type"] == "array"
    assert IMAGE["required"] is True
    assert IMAGE["min_items"] == 1
    assert set(ITEMS) == {"name", "prompt", "seed", "width", "height", *KNOB_FIELDS}
    assert ITEMS["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert ITEMS["seed"]["required"] is True
    assert ITEMS["seed"]["type"] == "integer"
    assert ITEMS["width"]["default"] == DEFAULT_WIDTH
    assert ITEMS["height"]["default"] == DEFAULT_HEIGHT
    for side in ("width", "height"):
        assert ITEMS[side]["min"] == SIDE_MIN
        assert ITEMS[side]["max"] == SIDE_MAX
    _assert_knob_fields(ITEMS, tuple(KNOB_FIELDS))


def test_the_workflow_input_is_an_enum_with_a_default() -> None:
    workflow = CAPABILITY["inputs"]["workflow"]
    assert workflow["type"] == "enum"
    assert workflow["values"] == ["z-image-turbo", "flux2-klein-4b"]
    assert workflow["default"] == "z-image-turbo"
    assert workflow["default"] in workflow["values"]


def test_the_edit_capability_is_an_image_from_a_reference() -> None:
    assert EDIT["kind"] == "image"
    assert EDIT["preview"]["viewer"] == "image"
    assert EDIT_SOURCE["type"] == "path"
    assert EDIT_SOURCE["required"] is True
    assert set(EDIT["inputs"]) == {"source", "image"}


def test_the_edit_entries_have_the_still_shape_and_defaults() -> None:
    assert set(EDIT_ITEMS) == {
        "name",
        "prompt",
        "seed",
        "width",
        "height",
        "steps",
        "cfg",
        "sampler",
    }
    # The img2img flow carries no scheduler and no shift.
    _assert_knob_fields(EDIT_ITEMS, ("steps", "cfg", "sampler"))
    assert EDIT_ITEMS["prompt"]["pattern"] == ITEMS["prompt"]["pattern"]
    for side in ("width", "height"):
        assert EDIT_ITEMS[side]["default"] == ITEMS[side]["default"]
        assert EDIT_ITEMS[side]["min"] == ITEMS[side]["min"]
        assert EDIT_ITEMS[side]["max"] == ITEMS[side]["max"]
    assert EDIT_ITEMS["width"]["default"] == DEFAULT_WIDTH
    assert EDIT_ITEMS["height"]["default"] == DEFAULT_HEIGHT
    assert EDIT["inputs"]["image"]["min_items"] == 1
    # The method is reference-guided: there is no denoise or strength knob.
    assert "workflow" not in EDIT["inputs"]
    assert "denoise" not in EDIT["inputs"]


def test_the_edit_flow_guides_the_latent_from_the_uploaded_image() -> None:
    graph = FLOW_IMG2IMG["graph"]
    assert graph["source"]["class_type"] == "LoadImage"
    assert graph["source"]["inputs"]["image"] == "$image"
    assert graph["reference"]["class_type"] == "ReferenceLatent"
    assert graph["reference"]["inputs"]["conditioning"] == ["positive_text", 0]
    assert graph["guider"]["inputs"]["positive"] == ["reference", 0]
    assert FLOW_IMG2IMG["uploads"] == ["image"]
    assert "denoise" not in json.dumps(graph)
    assert "denoise" not in json.dumps(FLOW_IMG2IMG["params"])
    placeholders = set(re.findall(r'"\$([a-z]+)"', json.dumps(graph)))
    assert placeholders == {
        "image",
        "prompt",
        "seed",
        "width",
        "height",
        "steps",
        "cfg",
        "sampler",
        "name",
    }


def test_the_edit_flow_loads_the_klein_models() -> None:
    graph = FLOW_IMG2IMG["graph"]
    assert graph["unet"]["inputs"]["unet_name"] == Path(LAB_MODELS["flux2-klein-unet"][2]).name
    assert graph["clip"]["inputs"]["clip_name"] == Path(LAB_MODELS["flux2-qwen-clip"][2]).name
    assert graph["vae"]["inputs"]["vae_name"] == Path(LAB_MODELS["flux2-klein-vae"][2]).name
    assert FLOW_IMG2IMG["params"]["steps"] == KLEIN_STEPS


def test_the_clip_capability_is_a_video_from_a_first_frame() -> None:
    assert CLIP["kind"] == "video"
    assert CLIP["preview"]["viewer"] == "video"
    assert set(CLIP["inputs"]) == {"image", "workflow"}
    image = CLIP["inputs"]["image"]
    assert image["type"] == "array"
    assert image["required"] is True
    assert image["min_items"] == 1


def test_the_clip_entries_carry_their_own_first_frame() -> None:
    assert set(CLIP_ITEMS) == {
        "name",
        "image",
        "prompt",
        "seed",
        "width",
        "height",
        "length",
        "negative",
        *KNOB_FIELDS,
    }
    _assert_knob_fields(CLIP_ITEMS, tuple(KNOB_FIELDS))
    assert CLIP_ITEMS["name"]["pattern"] == ITEMS["name"]["pattern"]
    assert CLIP_ITEMS["image"]["type"] == "path"
    assert CLIP_ITEMS["image"]["required"] is True
    assert CLIP_ITEMS["prompt"]["pattern"] == ITEMS["prompt"]["pattern"]
    assert CLIP_ITEMS["seed"]["required"] is True
    assert CLIP_ITEMS["seed"]["type"] == "integer"
    assert CLIP_ITEMS["width"]["default"] == DEFAULT_CLIP_WIDTH
    assert CLIP_ITEMS["height"]["default"] == DEFAULT_CLIP_HEIGHT
    assert CLIP_ITEMS["length"]["default"] == DEFAULT_CLIP_LENGTH


def test_the_clip_negative_is_an_optional_patternless_string() -> None:
    negative = CLIP_ITEMS["negative"]
    assert negative["type"] == "string"
    assert negative["required"] is False
    # A negative legitimately names text, subtitles and logos: no guard pattern.
    assert "pattern" not in negative
    assert "default" not in negative
    assert "default" in negative["description"]
    assert "fast" in negative["description"]


def test_still_and_edit_have_no_negative() -> None:
    assert "negative" not in ITEMS
    assert "negative" not in EDIT_ITEMS


def _assert_valid_clip_entry(entry: dict[str, object]) -> None:
    """The manifest's clip item schema, applied the way ``facet run`` does."""
    assert set(entry) <= set(CLIP_ITEMS)
    for key, field in CLIP_ITEMS.items():
        if field.get("required", False):
            assert key in entry, key
    assert re.fullmatch(CLIP_ITEMS["name"]["pattern"], str(entry["name"]))
    assert GUARD.fullmatch(str(entry["prompt"])) is not None
    assert isinstance(entry["seed"], int)
    for side in ("width", "height"):
        field = CLIP_ITEMS[side]
        value = entry.get(side, field.get("default"))
        assert field["min"] <= int(str(value)) <= field["max"]
    length = entry.get("length", CLIP_ITEMS["length"].get("default"))
    assert int(str(length)) % 4 == 1
    pattern = CLIP_ITEMS["negative"].get("pattern")
    if pattern is not None:
        assert re.fullmatch(pattern, str(entry.get("negative", ""))) is not None


def test_a_clip_piece_with_a_negative_validates() -> None:
    _assert_valid_clip_entry(
        {
            "name": "texforge-anim-c",
            "image": "texforge-lamina.png",
            "prompt": PLATE_PROMPT,
            "negative": PLATE_NEGATIVE,
            "seed": 11,
            "width": 1280,
            "height": 736,
            "length": 49,
        }
    )


def test_a_negative_naming_text_and_subtitles_validates() -> None:
    assert "text, subtitles" in PLATE_NEGATIVE
    assert "pattern" not in CLIP_ITEMS["negative"]
    _assert_valid_clip_entry(
        {
            "name": "bosque-niebla",
            "image": "fondo-video.png",
            "prompt": LAB_CLIP_PROMPTS[0],
            "negative": "static, blur, text, subtitles",
            "seed": 51,
        }
    )


def test_the_skill_teaches_the_engraved_plate_recipe() -> None:
    text = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "Animating an engraved plate" in text
    assert "wan22-i2v" in text
    assert PLATE_PROMPT in text
    assert PLATE_NEGATIVE in text


def test_the_skill_plate_example_validates() -> None:
    text = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```toml\n(.*?)```", text, re.DOTALL)
    pieces = [tomllib.loads(block) for block in blocks]
    matches = [
        entry
        for piece in pieces
        for entry in piece.get("inputs", {}).get("image", [])
        if entry.get("name") == "texforge-anim-c"
    ]
    assert len(matches) == 1
    entry = matches[0]
    assert entry["image"] == "texforge-lamina.png"
    assert entry["prompt"] == PLATE_PROMPT
    assert entry["negative"] == PLATE_NEGATIVE
    assert (entry["seed"], entry["width"], entry["height"], entry["length"]) == (11, 1280, 736, 49)
    _assert_valid_clip_entry(entry)


def test_the_clip_workflow_is_the_wan_enum() -> None:
    workflow = CLIP["inputs"]["workflow"]
    assert workflow["type"] == "enum"
    assert workflow["values"] == ["wan22-i2v", "wan22-i2v-fast"]
    assert workflow["default"] == "wan22-i2v"
    assert workflow["default"] in workflow["values"]
    assert "draft" in workflow["description"]


@pytest.mark.parametrize("word", GUARD_WORDS)
def test_the_guard_rejects_every_data_word(word: str) -> None:
    assert GUARD.fullmatch(f"A quiet {word} in the scene") is None
    assert GUARD.fullmatch(word.upper()) is None


def test_the_guard_rejects_a_data_word_in_caps() -> None:
    assert GUARD.fullmatch("A CHART") is None


@pytest.mark.parametrize("prompt", LAB_PROMPTS)
def test_the_guard_accepts_the_four_lab_prompts(prompt: str) -> None:
    assert GUARD.fullmatch(prompt) is not None


def test_the_edit_guard_accepts_the_lab_edit_prompt() -> None:
    assert GUARD.fullmatch(LAB_EDIT_PROMPT) is not None


@pytest.mark.parametrize("prompt", LAB_CLIP_PROMPTS)
def test_the_guard_accepts_the_three_lab_clip_prompts(prompt: str) -> None:
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
    assert FLOW["params"] == {
        "width": 1344,
        "height": 768,
        "seed": 0,
        "steps": 8,
        "shift": 3,
        "cfg": 1,
        "sampler": "res_multistep",
        "scheduler": "simple",
    }
    placeholders = set(re.findall(r'"\$([a-z]+)"', json.dumps(graph)))
    assert placeholders == {
        "prompt",
        "seed",
        "width",
        "height",
        "steps",
        "shift",
        "cfg",
        "sampler",
        "scheduler",
        "name",
    }


def test_the_klein_flow_fills_the_names_of_its_three_models() -> None:
    graph = FLOW_KLEIN["graph"]
    assert graph["unet"]["inputs"]["unet_name"] == Path(LAB_MODELS["flux2-klein-unet"][2]).name
    assert graph["clip"]["inputs"]["clip_name"] == Path(LAB_MODELS["flux2-qwen-clip"][2]).name
    assert graph["vae"]["inputs"]["vae_name"] == Path(LAB_MODELS["flux2-klein-vae"][2]).name
    assert FLOW_KLEIN["params"] == {
        "width": 1344,
        "height": 768,
        "seed": 0,
        "steps": 4,
        "cfg": 1,
        "sampler": "euler",
    }
    placeholders = set(re.findall(r'"\$([a-z]+)"', json.dumps(graph)))
    assert placeholders == {"prompt", "seed", "width", "height", "steps", "cfg", "sampler", "name"}


def test_the_wan_flow_animates_the_uploaded_still() -> None:
    graph = FLOW_WAN["graph"]
    assert graph["unet"]["inputs"]["unet_name"] == Path(LAB_MODELS["wan2v2-unet"][2]).name
    assert graph["clip"]["inputs"]["clip_name"] == Path(LAB_MODELS["wan2v2-clip"][2]).name
    assert graph["vae"]["inputs"]["vae_name"] == Path(LAB_MODELS["wan2v2-vae"][2]).name
    assert graph["start"]["class_type"] == "LoadImage"
    assert graph["start"]["inputs"]["image"] == "$image"
    assert graph["latent"]["class_type"] == "Wan22ImageToVideoLatent"
    assert graph["latent"]["inputs"]["start_image"] == ["start", 0]
    assert FLOW_WAN["uploads"] == ["image"]
    assert FLOW_WAN["comfy_args"] == ["--disable-pinned-memory"]


def test_the_wan_flow_params_are_the_lab_clip() -> None:
    params = FLOW_WAN["params"]
    assert set(params) == {
        "width",
        "height",
        "length",
        "seed",
        "steps",
        "cfg",
        "shift",
        "sampler",
        "scheduler",
        "fps",
        "negative",
    }
    assert (params["width"], params["height"], params["length"]) == (
        DEFAULT_CLIP_WIDTH,
        DEFAULT_CLIP_HEIGHT,
        DEFAULT_CLIP_LENGTH,
    )
    assert (params["steps"], params["cfg"], params["shift"], params["fps"]) == (20, 5, 8, 24)
    assert (params["sampler"], params["scheduler"]) == ("uni_pc", "simple")
    assert params["negative"].strip()
    placeholders = set(re.findall(r'"\$([a-z]+)"', json.dumps(FLOW_WAN["graph"])))
    assert placeholders == {
        "image",
        "prompt",
        "negative",
        "width",
        "height",
        "length",
        "seed",
        "steps",
        "cfg",
        "shift",
        "sampler",
        "scheduler",
        "fps",
        "name",
    }


def _knob_inputs(graph: dict[str, Any]) -> dict[str, list[object]]:
    """Every sampler knob the graph carries, by the input's name."""
    found: dict[str, list[object]] = {}
    for body in graph.values():
        inputs = body.get("inputs", {})
        for key in KNOB_INPUTS:
            if key in inputs:
                found.setdefault(key, []).append(inputs[key])
    return found


def test_every_flow_has_each_knob_as_a_placeholder_with_todays_default() -> None:
    for flow_name, knobs in FLOW_KNOBS.items():
        data = json.loads((PACKAGE / "flows" / f"{flow_name}.json").read_text(encoding="utf-8"))
        for knob, default in knobs.items():
            assert data["params"][knob] == default, (flow_name, knob)
        found = _knob_inputs(data["graph"])
        assert {"steps", "cfg", "sampler_name"} <= set(found), flow_name
        for input_key, values in found.items():
            knob = KNOB_INPUTS[input_key]
            assert knob in knobs, (flow_name, input_key)
            # Every carrier is a placeholder, never a literal left in the flow.
            assert values == [f"${knob}"] * len(values), (flow_name, input_key, values)
        for optional in ("scheduler", "shift"):
            assert (optional in found) == (optional in knobs), (flow_name, optional)


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


def test_the_skill_documents_the_flows_and_the_server() -> None:
    text = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
    for flow in (
        "z-image-turbo",
        "flux2-klein-4b",
        "flux2-klein-img2img",
        "wan22-i2v",
        "wan22-i2v-fast",
    ):
        assert flow in text
    assert "--disable-pinned-memory" in text
    assert "GSAP" in text
    assert "Apache-2.0" in text
    assert "GPL-3.0-or-later" in text
    # comfy_args is inert in this registry: runner.py never reads it.
    assert "comfy_args" not in text


EXAMPLE_FILES = (
    "examples/z-image-turbo/imagenes.toml",
    "examples/z-image-turbo/fondo-video.png",
    "examples/z-image-turbo/ilustracion-editorial.png",
    "examples/z-image-turbo/foto-producto.png",
    "examples/z-image-turbo/acuarela.png",
    "examples/img2img.toml",
    "examples/iteracion-grabado.png",
    "examples/README-img2img.md",
    "examples/comparacion.jpg",
    "examples/flux2-klein-4b/ilustracion-editorial.png",
    "examples/flux2-klein-4b/acuarela.png",
    "examples/clips.toml",
    "examples/bosque-niebla.mp4",
    "examples/taza-vapor.mp4",
    "examples/calle-acuarela.mp4",
    "examples/bosque-niebla-rapido.mp4",
)


def test_the_skill_references_and_examples_exist() -> None:
    for name in ("flows.md", "server.md", "seeds.md"):
        path = PACKAGE / "references" / name
        assert path.is_file(), name
        assert path.stat().st_size > 0, name
    for name in EXAMPLE_FILES:
        path = PACKAGE / name
        assert path.is_file(), name
        assert path.stat().st_size > 0, name
