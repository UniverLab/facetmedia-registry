"""The comfy-xl manifest: the server pin, the twelve models and the prompt guard.

The registry suite runs without the core, so the checks here read the
manifest and the flows as data. The closed item set pins what the core turns
into ``invalid_input``: each capability's items are pinned exactly, so a
piece that adds a key the manifest does not declare is rejected before
anything runs. The guard is the manifest's own ``pattern``, applied the way
``facetmedia.schema`` applies it (``re.fullmatch``).
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "comfy-xl"
COMFY = ROOT / "packages" / "comfy"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
COMFY_MANIFEST = tomllib.loads((COMFY / "package.toml").read_text(encoding="utf-8"))
INDEX = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
FLOW = json.loads((PACKAGE / "flows" / "z-image.json").read_text(encoding="utf-8"))
FLOW_EDIT = json.loads((PACKAGE / "flows" / "qwen-image-edit.json").read_text(encoding="utf-8"))
FLOW_WAN = json.loads((PACKAGE / "flows" / "wan22-i2v-14b.json").read_text(encoding="utf-8"))
FLOW_RAPIDO = json.loads(
    (PACKAGE / "flows" / "wan22-i2v-14b-fast.json").read_text(encoding="utf-8")
)
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
VRAM_GB = 24
RAM_GB = 32
DISK_GB = 95
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 768
DEFAULT_CLIP_WIDTH = 1280
DEFAULT_CLIP_HEIGHT = 704
DEFAULT_CLIP_LENGTH = 49
EDIT_STEPS = 40
EDIT_CFG = 4
EDIT_SHIFT = 3.1
STEPS = 25
SHIFT = 3
CFG = 4
WAN_STEPS = 20
WAN_CFG = 5
WAN_SHIFT = 8
RAPIDO_STEPS = 4
RAPIDO_CFG = 1
RAPIDO_STRENGTH = 1.0
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
    "z-image": {
        "steps": STEPS,
        "cfg": CFG,
        "sampler": "res_multistep",
        "scheduler": "simple",
        "shift": SHIFT,
    },
    "qwen-image-edit": {
        "steps": EDIT_STEPS,
        "cfg": EDIT_CFG,
        "sampler": "euler",
        "scheduler": "simple",
        "shift": EDIT_SHIFT,
    },
    "wan22-i2v-14b": {
        "steps": WAN_STEPS,
        "cfg": WAN_CFG,
        "sampler": "euler",
        "scheduler": "simple",
        "shift": WAN_SHIFT,
    },
    "wan22-i2v-14b-fast": {
        "steps": RAPIDO_STEPS,
        "cfg": RAPIDO_CFG,
        "sampler": "euler",
        "scheduler": "simple",
        "shift": WAN_SHIFT,
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

#: Two prompts in the lab's approved style: illustration, never data.
LAB_PROMPTS = (
    "Misty pine forest at dawn, soft volumetric light through the trees, muted teal and "
    "amber palette, wide establishing shot, large empty area of fog on the left side, "
    "cinematic, calm",
    "Loose watercolor painting of a colonial street in a small Andean town, colorful "
    "facades with wooden balconies, cobblestones, green mountains in the background, "
    "visible paper texture and pigment blooms",
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

#: The twelve models the pull downloads, pinned by URL, sha256, size and path.
#: ``z-image-base-*`` carry a base prefix because the core rejects a model id
#: declared by two packages, and ``comfy`` already owns ``z-image-qwen-clip``
#: and ``z-image-vae`` for its own turbo files.
LAB_MODELS = {
    "z-image-unet": (
        "https://huggingface.co/Comfy-Org/Z-Image/resolve/"
        "94d47a468ec820d29a5dc09d4642539d76d49542/"
        "split_files/diffusion_models/z_image_bf16.safetensors",
        "996a67d3ff666946b1c25cbc16d1b1918b6cc0ac166309e23fe3b3d830263dee",
        12309866400,
        "z-image-unet/z_image_bf16.safetensors",
    ),
    "z-image-base-qwen-clip": (
        "https://huggingface.co/Comfy-Org/Z-Image/resolve/"
        "94d47a468ec820d29a5dc09d4642539d76d49542/"
        "split_files/text_encoders/qwen_3_4b.safetensors",
        "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a",
        8044982048,
        "z-image-base-qwen-clip/qwen_3_4b.safetensors",
    ),
    "z-image-base-vae": (
        "https://huggingface.co/Comfy-Org/Z-Image/resolve/"
        "94d47a468ec820d29a5dc09d4642539d76d49542/split_files/vae/ae.safetensors",
        "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
        335304388,
        "z-image-base-vae/ae.safetensors",
    ),
    "wan14b-high-unet": (
        "https://huggingface.co/Comfy-Org/Wan-2.2/resolve/"
        "ee6f4a40737a995bf5818954cfce6d59443b0f04/"
        "split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        "6122e79d55e0f235698d11d657f3b196c5273c830da00b2b013c5a048d5e6a42",
        14294742832,
        "wan14b-high-unet/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    ),
    "wan14b-low-unet": (
        "https://huggingface.co/Comfy-Org/Wan-2.2/resolve/"
        "ee6f4a40737a995bf5818954cfce6d59443b0f04/"
        "split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
        "5471a457b6ac404202a5fbe6c11595a3d5641fc766b00f38763f72303fffc21e",
        14294742832,
        "wan14b-low-unet/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    ),
    "wan14b-clip": (
        "https://huggingface.co/Comfy-Org/Wan-2.2/resolve/"
        "ee6f4a40737a995bf5818954cfce6d59443b0f04/"
        "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
        6735906897,
        "wan14b-clip/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    ),
    "wan14b-vae": (
        "https://huggingface.co/Comfy-Org/Wan-2.2/resolve/"
        "ee6f4a40737a995bf5818954cfce6d59443b0f04/split_files/vae/wan_2.1_vae.safetensors",
        "2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b",
        253815318,
        "wan14b-vae/wan_2.1_vae.safetensors",
    ),
    "wan14b-lightx2v-high": (
        "https://huggingface.co/Comfy-Org/Wan-2.2/resolve/"
        "ee6f4a40737a995bf5818954cfce6d59443b0f04/"
        "split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
        "d176c808d6fc461999b68e321efcb7501b20b8c3797523ed0df14f7d1deff11e",
        1226977424,
        "wan14b-lightx2v-high/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
    ),
    "wan14b-lightx2v-low": (
        "https://huggingface.co/Comfy-Org/Wan-2.2/resolve/"
        "ee6f4a40737a995bf5818954cfce6d59443b0f04/"
        "split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
        "024f21de095bc8fad9809ded3e9e49a2e170dcf27075da8145ba7d60d8aab7f9",
        1226977424,
        "wan14b-lightx2v-low/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
    ),
    "qwen-edit-unet": (
        "https://huggingface.co/Comfy-Org/Qwen-Image-Edit/resolve/"
        "f68ace85e60b4a02a323e394253731947657b7d2/"
        "split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors",
        "c9fdc158e46d3b61ef75f21ae866ca2fe808bf4a53643120d1c1e87c19280a4e",
        20533762817,
        "qwen-edit-unet/qwen_image_edit_2511_fp8mixed.safetensors",
    ),
    "qwen-edit-clip": (
        "https://huggingface.co/Comfy-Org/Qwen-Image/resolve/"
        "1f12b17be14c89b026c51a91d67c32f84bb047bc/"
        "split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
        "cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4",
        9384670680,
        "qwen-edit-clip/qwen_2.5_vl_7b_fp8_scaled.safetensors",
    ),
    "qwen-edit-vae": (
        "https://huggingface.co/Comfy-Org/Qwen-Image/resolve/"
        "1f12b17be14c89b026c51a91d67c32f84bb047bc/split_files/vae/qwen_image_vae.safetensors",
        "a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f",
        253806246,
        "qwen-edit-vae/qwen_image_vae.safetensors",
    ),
}


def test_index_lists_the_comfy_xl_package() -> None:
    names = [entry["name"] for entry in INDEX["packages"]]
    assert "comfy-xl" in names


def test_the_package_declares_the_shared_comfy_client() -> None:
    assert MANIFEST["uses"] == ["comfyclient"]
    assert (ROOT / "lib" / "comfyclient.py").is_file()


def test_the_package_is_the_image_facet_with_still_edit_and_clip() -> None:
    assert MANIFEST["name"] == "comfy-xl"
    assert MANIFEST["facet"] == "image"
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    assert sorted(MANIFEST["capabilities"]) == ["clip", "edit", "still"]
    assert CAPABILITY["kind"] == "image"
    assert CAPABILITY["preview"]["viewer"] == "image"
    assert CLIP["kind"] == "video"
    assert CLIP["preview"]["viewer"] == "video"


def test_the_server_is_the_pinned_comfyui_shared_with_comfy() -> None:
    assert MANIFEST["engine"] == COMFY_MANIFEST["engine"]
    server = MANIFEST["engine"]["server"]
    assert server["repo"] == "https://github.com/comfyanonymous/ComfyUI.git"
    assert server["rev"] == "3c1b7a17fdf239d35ce98cc777756f572d089795"
    assert server["launch"][:2] == ["python", "main.py"]
    assert "--disable-pinned-memory" in server["launch"]
    assert any("{{port}}" in token for token in server["launch"])
    assert server["health_url"] == "http://127.0.0.1:{{port}}/system_stats"


def test_the_requirements_are_one_24gb_gpu_job() -> None:
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is True
    assert requirements["vram_gb"] == VRAM_GB
    assert requirements["ram_gb"] == RAM_GB
    assert requirements["disk_gb"] == DISK_GB
    assert "exclusive" not in requirements
    assert "platforms" not in requirements


def test_the_twelve_models_are_the_lab_files() -> None:
    models = {model["id"]: model for model in MANIFEST["models"]}
    assert set(models) == set(LAB_MODELS)
    for model_id, (url, sha256, size, path) in LAB_MODELS.items():
        model = models[model_id]
        assert model["url"] == url
        assert model["sha256"] == sha256
        assert model["bytes"] == size
        assert model["path"] == path
        assert model["spdx"] == "Apache-2.0"
        assert model["commercial_use"] is True
        assert model["requires_acceptance"] is False
        # Per-file entries: an HF entry would download the whole revision.
        assert "hf_repo" not in model


def test_the_description_marks_the_unrun_hardware() -> None:
    assert MANIFEST["description"].endswith("(not yet run on a 24 GB GPU).")


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


def test_the_workflow_input_is_the_one_still_flow() -> None:
    workflow = CAPABILITY["inputs"]["workflow"]
    assert workflow["type"] == "enum"
    assert workflow["values"] == ["z-image"]
    assert "default" not in workflow
    assert "z-image" in workflow["description"]


def test_every_capability_takes_an_optional_flow() -> None:
    assert set(CAPABILITY["inputs"]) == {"image", "workflow", "flow"}
    for capability in (CAPABILITY, EDIT, CLIP):
        flow = capability["inputs"]["flow"]
        assert flow["type"] == "path"
        assert flow["required"] is False
    assert "Exclusive with workflow" in CAPABILITY["inputs"]["flow"]["description"]
    assert "Exclusive with workflow" in CLIP["inputs"]["flow"]["description"]


def test_the_edit_capability_is_an_image_from_a_reference() -> None:
    assert EDIT["kind"] == "image"
    assert EDIT["preview"]["viewer"] == "image"
    assert EDIT_SOURCE["type"] == "path"
    assert EDIT_SOURCE["required"] is True
    assert set(EDIT["inputs"]) == {"source", "image", "flow"}


def test_the_edit_entries_have_the_still_shape_and_defaults() -> None:
    assert set(EDIT_ITEMS) == {"name", "prompt", "seed", "width", "height", *KNOB_FIELDS}
    _assert_knob_fields(EDIT_ITEMS, tuple(KNOB_FIELDS))
    assert EDIT_ITEMS["prompt"]["pattern"] == ITEMS["prompt"]["pattern"]
    for side in ("width", "height"):
        assert EDIT_ITEMS[side]["default"] == ITEMS[side]["default"]
        assert EDIT_ITEMS[side]["min"] == ITEMS[side]["min"]
        assert EDIT_ITEMS[side]["max"] == ITEMS[side]["max"]
    assert EDIT["inputs"]["image"]["min_items"] == 1
    # The method is reference-guided: there is no denoise or strength knob.
    assert "workflow" not in EDIT["inputs"]
    assert "denoise" not in EDIT["inputs"]


def test_the_edit_flow_guides_the_latent_from_the_uploaded_image() -> None:
    graph = FLOW_EDIT["graph"]
    assert graph["source"]["class_type"] == "LoadImage"
    assert graph["source"]["inputs"]["image"] == "$image"
    assert graph["sized"]["class_type"] == "ImageScale"
    assert graph["sized"]["inputs"]["width"] == "$width"
    assert graph["sized"]["inputs"]["height"] == "$height"
    assert graph["positive_encode"]["class_type"] == "TextEncodeQwenImageEditPlus"
    assert graph["positive_encode"]["inputs"]["prompt"] == "$prompt"
    assert graph["positive_encode"]["inputs"]["image1"] == ["sized", 0]
    assert graph["negative_encode"]["inputs"]["prompt"] == ""
    assert graph["positive_method"]["class_type"] == "FluxKontextMultiReferenceLatentMethod"
    assert graph["positive_method"]["inputs"]["conditioning"] == ["positive_encode", 0]
    assert graph["negative_method"]["inputs"]["conditioning"] == ["negative_encode", 0]
    assert graph["latent"]["class_type"] == "VAEEncode"
    assert graph["latent"]["inputs"]["pixels"] == ["sized", 0]
    assert graph["sampler"]["inputs"]["latent_image"] == ["latent", 0]
    assert graph["sampler"]["inputs"]["positive"] == ["positive_method", 0]
    assert graph["sampler"]["inputs"]["negative"] == ["negative_method", 0]
    assert graph["sampler"]["inputs"]["denoise"] == 1
    assert graph["cfg_norm"]["class_type"] == "CFGNorm"
    assert graph["model_shift"]["class_type"] == "ModelSamplingAuraFlow"
    assert "LoraLoader" not in json.dumps(graph)
    assert FLOW_EDIT["uploads"] == ["image"]
    assert "denoise" not in FLOW_EDIT["params"]
    placeholders = set(re.findall(r'"\$([a-z_]+)"', json.dumps(graph)))
    assert placeholders == {
        "image",
        "prompt",
        "seed",
        "width",
        "height",
        "steps",
        "cfg",
        "shift",
        "sampler",
        "scheduler",
        "name",
    }


def test_the_edit_flow_loads_the_qwen_models() -> None:
    graph = FLOW_EDIT["graph"]
    assert graph["unet"]["inputs"]["unet_name"] == Path(LAB_MODELS["qwen-edit-unet"][3]).name
    assert graph["clip"]["inputs"]["clip_name"] == Path(LAB_MODELS["qwen-edit-clip"][3]).name
    assert graph["vae"]["inputs"]["vae_name"] == Path(LAB_MODELS["qwen-edit-vae"][3]).name
    assert FLOW_EDIT["params"]["steps"] == EDIT_STEPS
    assert FLOW_EDIT["params"]["cfg"] == EDIT_CFG
    assert FLOW_EDIT["params"]["shift"] == EDIT_SHIFT
    assert FLOW_EDIT["params"]["sampler"] == "euler"
    assert FLOW_EDIT["params"]["scheduler"] == "simple"


def test_the_clip_capability_is_a_video_from_a_first_frame() -> None:
    assert CLIP["kind"] == "video"
    assert CLIP["preview"]["viewer"] == "video"
    assert set(CLIP["inputs"]) == {"image", "workflow", "flow"}
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
            "name": "bosque-niebla",
            "image": "fondo-video.png",
            "prompt": PLATE_PROMPT,
            "negative": PLATE_NEGATIVE,
            "seed": 51,
            "width": 1280,
            "height": 704,
            "length": 49,
        }
    )


def test_a_negative_naming_text_and_subtitles_validates() -> None:
    assert "text, subtitles" in PLATE_NEGATIVE
    assert "pattern" not in CLIP_ITEMS["negative"]
    _assert_valid_clip_entry(
        {
            "name": "taza-vapor",
            "image": "taza.png",
            "prompt": LAB_PROMPTS[0],
            "negative": "static, blur, text, subtitles",
            "seed": 52,
        }
    )


def test_the_skill_teaches_the_24gb_card() -> None:
    text = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    assert "24 GB of VRAM" in flat
    assert "have not yet been run on such a GPU by the lab" in flat
    assert "On an 8 GB card, use `comfy` instead." in flat


def test_the_clip_workflow_is_the_14b_enum() -> None:
    workflow = CLIP["inputs"]["workflow"]
    assert workflow["type"] == "enum"
    assert workflow["values"] == ["wan22-i2v-14b", "wan22-i2v-14b-fast"]
    assert "default" not in workflow
    assert "wan22-i2v-14b" in workflow["description"]
    assert "draft" in workflow["description"]


@pytest.mark.parametrize("word", GUARD_WORDS)
def test_the_guard_rejects_every_data_word(word: str) -> None:
    assert GUARD.fullmatch(f"A quiet {word} in the scene") is None
    assert GUARD.fullmatch(word.upper()) is None


def test_the_guard_rejects_a_data_word_in_caps() -> None:
    assert GUARD.fullmatch("A CHART") is None


@pytest.mark.parametrize("prompt", LAB_PROMPTS)
def test_the_guard_accepts_the_lab_prompts(prompt: str) -> None:
    assert GUARD.fullmatch(prompt) is not None


def test_the_guard_keeps_texture_digits_and_longer_words() -> None:
    assert GUARD.fullmatch("subtle paper grain texture, 85mm lens") is not None
    # "photograph" holds "graph" and "design" holds "sign": whole words only.
    assert GUARD.fullmatch("a photograph of a design") is not None


def test_the_flow_fills_the_names_of_the_three_models() -> None:
    graph = FLOW["graph"]
    assert graph["unet"]["inputs"]["unet_name"] == Path(LAB_MODELS["z-image-unet"][3]).name
    assert (
        graph["clip"]["inputs"]["clip_name"] == Path(LAB_MODELS["z-image-base-qwen-clip"][3]).name
    )
    assert graph["vae"]["inputs"]["vae_name"] == Path(LAB_MODELS["z-image-base-vae"][3]).name
    assert FLOW["params"] == {
        "width": 1344,
        "height": 768,
        "seed": 0,
        "steps": STEPS,
        "shift": SHIFT,
        "cfg": CFG,
        "sampler": "res_multistep",
        "scheduler": "simple",
    }
    placeholders = set(re.findall(r'"\$([a-z_]+)"', json.dumps(graph)))
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


def test_the_wan_flow_samples_high_noise_then_low_noise() -> None:
    graph = FLOW_WAN["graph"]
    assert graph["unet_high"]["inputs"]["unet_name"] == Path(LAB_MODELS["wan14b-high-unet"][3]).name
    assert graph["unet_low"]["inputs"]["unet_name"] == Path(LAB_MODELS["wan14b-low-unet"][3]).name
    assert graph["clip"]["inputs"]["clip_name"] == Path(LAB_MODELS["wan14b-clip"][3]).name
    assert graph["vae"]["inputs"]["vae_name"] == Path(LAB_MODELS["wan14b-vae"][3]).name
    assert graph["start"]["class_type"] == "LoadImage"
    assert graph["start"]["inputs"]["image"] == "$image"
    assert graph["i2v"]["class_type"] == "WanImageToVideo"
    assert graph["i2v"]["inputs"]["positive"] == ["positive", 0]
    assert graph["i2v"]["inputs"]["negative"] == ["negative", 0]
    assert graph["i2v"]["inputs"]["start_image"] == ["start", 0]
    for name in ("sampler_high", "sampler_low"):
        assert graph[name]["inputs"]["positive"] == ["i2v", 0]
        assert graph[name]["inputs"]["negative"] == ["i2v", 1]
    assert graph["sampler_high"]["inputs"]["latent_image"] == ["i2v", 2]
    assert graph["sampler_low"]["inputs"]["latent_image"] == ["sampler_high", 0]
    assert graph["sampler_low"]["inputs"]["add_noise"] == "disable"
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
    assert (params["steps"], params["cfg"], params["shift"], params["fps"]) == (
        WAN_STEPS,
        WAN_CFG,
        WAN_SHIFT,
        24,
    )
    assert (params["sampler"], params["scheduler"]) == ("euler", "simple")
    assert params["negative"].strip()
    placeholders = set(re.findall(r'"\$([a-z_]+)"', json.dumps(FLOW_WAN["graph"])))
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


def test_the_rapido_flow_adds_both_lightx2v_loras() -> None:
    graph = FLOW_RAPIDO["graph"]
    high = Path(LAB_MODELS["wan14b-lightx2v-high"][3]).name
    low = Path(LAB_MODELS["wan14b-lightx2v-low"][3]).name
    assert graph["lora_high"]["inputs"]["lora_name"] == high
    assert graph["lora_low"]["inputs"]["lora_name"] == low
    assert graph["model_high"]["inputs"]["model"] == ["lora_high", 0]
    assert graph["model_low"]["inputs"]["model"] == ["lora_low", 0]
    assert graph["i2v"]["class_type"] == "WanImageToVideo"
    assert graph["sampler_high"]["inputs"]["latent_image"] == ["i2v", 2]
    assert graph["sampler_low"]["inputs"]["latent_image"] == ["sampler_high", 0]
    assert graph["sampler_high"]["inputs"]["steps"] == "$steps"
    assert graph["sampler_low"]["inputs"]["cfg"] == "$cfg"
    assert FLOW_RAPIDO["params"]["steps"] == RAPIDO_STEPS
    assert FLOW_RAPIDO["params"]["cfg"] == RAPIDO_CFG
    assert FLOW_RAPIDO["params"]["lora_strength"] == RAPIDO_STRENGTH
    placeholders = set(re.findall(r'"\$([a-z_]+)"', json.dumps(graph)))
    assert "lora_strength" in placeholders


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


def test_every_flow_model_file_exists_in_the_model_paths() -> None:
    paths = {model["path"] for model in MANIFEST["models"]}
    names = {Path(path).name for path in paths}
    for flow in (FLOW, FLOW_EDIT, FLOW_WAN, FLOW_RAPIDO):
        text = json.dumps(flow["graph"])
        for key in ("unet_name", "clip_name", "vae_name", "lora_name"):
            for name in re.findall(rf'"{key}": "([^"]+)"', text):
                assert name in names, name


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
    assert meta["name"] == "comfy-xl"
    assert DESCRIPTION_MIN <= len(meta["description"]) <= DESCRIPTION_MAX
    headings = [
        line.removeprefix("## ").strip() for line in lines[end + 1 :] if line.startswith("## ")
    ]
    required = ["When to use", "Pieces", "Judging the result", "Pitfalls"]
    assert [heading for heading in headings if heading in required] == required
    assert "comfy-xl.still" in text


def test_the_skill_documents_the_flows_and_the_server() -> None:
    text = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
    for flow in (
        "z-image",
        "qwen-image-edit",
        "wan22-i2v-14b",
        "wan22-i2v-14b-fast",
    ):
        assert flow in text
    assert "--disable-pinned-memory" in text
    assert "GSAP" in text
    assert "Apache-2.0" in text
    assert "GPL-3.0-or-later" in text
    # comfy_args is inert in this registry: runner.py never reads it.
    assert "comfy_args" not in text


def test_the_skill_references_exist() -> None:
    for name in ("flows.md", "server.md", "seeds.md"):
        path = PACKAGE / "references" / name
        assert path.is_file(), name
        assert path.stat().st_size > 0, name


def test_the_skill_teaches_your_own_flow() -> None:
    text = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "Your own flow" in text
    assert "uploads" in text
    assert "VRAM" in text
