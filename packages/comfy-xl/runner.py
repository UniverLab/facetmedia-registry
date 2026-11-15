"""The comfy-xl package runner: stills, edits and clips with ComfyUI.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull). ``run`` links facet's models into the pinned ComfyUI
checkout, fills the selected flow's graph and downloads the PNGs (or the MP4
of a clip) it produced; an edit flow uploads the piece's reference image
first and a clip uploads each entry's first frame, filling ``$image`` with
the name the server answered; ``verify`` opens every PNG with Pillow (and
every clip with FFmpeg) and checks its pixel size (and its resolution, frame
rate and frame count); ``preview`` writes the preview file of the asset's
kind; ``doctor`` checks the GPU, the models and the checkout at ``quick`` and
probes the server at ``full``.

ComfyUI itself is a ``[engine.server]``: facet clones the pinned revision,
builds its venv and starts ``main.py`` for the duration of the verb, passing
the free port and the base URL through ``{{port}}`` and ``FACET_SERVER_URL``.

The package-agnostic ComfyUI client (server calls, flows, video probe and
doctor checks) lives in the registry's shared module ``comfyclient``,
pulled into the environment as ``facet_lib.comfyclient``; this runner keeps
only comfy-xl's flows, sizes, model map and thin entry-point wiring.
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Any

import PIL.Image
from facet_lib import comfyclient
from facet_runner_sdk import Request, Runner

runner = Runner()

PACKAGE_DIR = Path(__file__).parent

#: The lab's 24 GB flows: Z-Image base at full precision.
FLOW_NAMES = ("z-image",)
DEFAULT_WORKFLOW = "z-image"
#: The one flow an edit uses: reference-guided, no denoise strength.
EDIT_FLOW = "qwen-image-edit"
#: The flows a clip uses: Wan 2.2 I2V 14B animating what is inside a still.
CLIP_FLOW_NAMES = ("wan22-i2v-14b", "wan22-i2v-14b-fast")
#: The half-time flow whose output is a draft, never a final render.
DRAFT_FLOW = "wan22-i2v-14b-fast"
#: What a draft asset's name carries before its suffix: ``<name>-borrador.mp4``.
DRAFT_SUFFIX = "borrador"
STILL_CAPABILITY = "comfy-xl.still"
EDIT_CAPABILITY = "comfy-xl.edit"
CLIP_CAPABILITY = "comfy-xl.clip"
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 768
DEFAULT_CLIP_WIDTH = 1280
DEFAULT_CLIP_HEIGHT = 704
DEFAULT_CLIP_LENGTH = 49
#: Wan 2.2 I2V 14B renders 24 fps; verify holds the clip to it.
VIDEO_FPS = 24
VIDEO_FPS_TOLERANCE = 0.01
PULL_FIX = "facet pull comfy-xl"
#: Model id -> the directory of the checkout ComfyUI loads that kind from.
MODEL_DIRS = {
    "z-image-unet": "models/diffusion_models",
    "z-image-base-qwen-clip": "models/text_encoders",
    "z-image-base-vae": "models/vae",
    "wan14b-high-unet": "models/diffusion_models",
    "wan14b-low-unet": "models/diffusion_models",
    "wan14b-clip": "models/text_encoders",
    "wan14b-vae": "models/vae",
    "wan14b-lightx2v-high": "models/loras",
    "wan14b-lightx2v-low": "models/loras",
    "qwen-edit-unet": "models/diffusion_models",
    "qwen-edit-clip": "models/text_encoders",
    "qwen-edit-vae": "models/vae",
}


def _save(
    images: list[dict[str, Any]], name: str, out_dir: Path, draft: bool = False
) -> list[Path]:
    """Download every output beside the piece; one image keeps the plain name.

    A draft names its file ``<name>-borrador`` so a draft never passes for a
    final render.
    """
    saved: list[Path] = []
    marker = f"-{DRAFT_SUFFIX}" if draft else ""
    for index, image in enumerate(images):
        query = urllib.parse.urlencode(
            {key: image[key] for key in ("filename", "subfolder", "type")}
        )
        suffix = Path(str(image["filename"])).suffix or ".png"
        if len(images) == 1:
            stem = f"{name}{marker}{suffix}"
        else:
            stem = f"{name}{marker}-{index + 1}{suffix}"
        target = out_dir / stem
        target.write_bytes(comfyclient.get_bytes(f"/view?{query}"))
        saved.append(target)
    return saved


def _asset(
    entry: dict[str, Any], path: Path, video: bool = False, draft: bool = False
) -> dict[str, Any]:
    """One record: the values actually used as its params, the seed beside them.

    ``entry`` is the flow params merged with the entry, so the record shows
    the defaults the flow supplied. A still is the ``image`` kind, a clip the
    ``video`` kind with the same measured width and height. A draft clip marks
    its properties so no assembly mistakes it for a final.
    """
    seed = int(entry["seed"])
    kind, mime = ("video", "video/mp4") if video else ("image", "image/png")
    properties: dict[str, Any] = {
        "width": int(entry.get("width", DEFAULT_CLIP_WIDTH if video else DEFAULT_WIDTH)),
        "height": int(entry.get("height", DEFAULT_CLIP_HEIGHT if video else DEFAULT_HEIGHT)),
        "seed": seed,
    }
    if draft:
        properties["draft"] = True
    return {
        "file": path.name,
        "name": str(entry["name"]),
        "kind": kind,
        "mime": mime,
        "properties": properties,
        "params": dict(entry),
        "seed": seed,
        "inputs": [],
    }


def _flow_name(capability: str, inputs: dict[str, Any]) -> str:
    """The flow the request asks for: an edit is always the img2img one."""
    if capability == EDIT_CAPABILITY:
        return EDIT_FLOW
    if capability == CLIP_CAPABILITY:
        names, fallback = CLIP_FLOW_NAMES, CLIP_FLOW_NAMES[0]
    else:
        names, fallback = FLOW_NAMES, DEFAULT_WORKFLOW
    workflow = str(inputs.get("workflow", fallback))
    if workflow not in names:
        raise ValueError(f"unknown workflow: {workflow}")
    return workflow


def _load_flow(req: Request, inputs: dict[str, Any]) -> tuple[dict[str, Any], bool, dict[str, str]]:
    """The flow to run: the piece's own file, or one of the package's.

    ``flow`` and ``workflow`` are mutually exclusive; a custom flow is never
    a draft, and its record carries the file's path and sha256.
    """
    raw = inputs.get("flow")
    if raw is not None and inputs.get("workflow") is not None:
        raise ValueError("give either flow or workflow, not both")
    if raw is not None:
        path = comfyclient.flow_path(req)
        return (
            comfyclient.custom_flow(path),
            False,
            {"flow": str(path), "flow_sha256": comfyclient.flow_digest(path)},
        )
    name = _flow_name(req.capability, inputs)
    return comfyclient.flow(PACKAGE_DIR / "flows", name), name == DRAFT_FLOW, {}


def _source_path(flow: dict[str, Any], inputs: dict[str, Any]) -> Path | None:
    """The piece's reference image, when the flow uploads one."""
    uploads = flow.get("uploads")
    if not isinstance(uploads, list) or "image" not in uploads:
        return None
    source = inputs.get("source")
    if not source:
        raise ValueError("the piece has no source image")
    return Path(str(source))


def _entry_list(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """The piece's ``image`` array, one dict per entry."""
    raw = inputs.get("image")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _entry_image(req: Request, entry: dict[str, Any]) -> Path:
    """A clip entry's first frame; the core resolves it, this keeps one relative."""
    path = Path(str(entry["image"]))
    return path if path.is_absolute() else req.piece_dir / path


def _upload_entry(req: Request, entry: dict[str, Any]) -> str:
    """Upload one clip's first frame; the server's name is what LoadImage wants."""
    source = _entry_image(req, entry)
    uploaded = comfyclient.upload(source)
    print(f"{source.name} uploaded as {uploaded}", flush=True)
    return uploaded


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    if req.capability not in (STILL_CAPABILITY, EDIT_CAPABILITY, CLIP_CAPABILITY):
        raise ValueError(f"unknown capability: {req.capability}")
    inputs = dict(req.inputs)
    entries = _entry_list(inputs)
    if not entries:
        raise ValueError("the piece has no image entries")
    video = req.capability == CLIP_CAPABILITY
    manifest = comfyclient.manifest(PACKAGE_DIR)
    flow, draft, meta = _load_flow(req, inputs)
    planned = [comfyclient.values(flow, entry) for entry in entries]
    allowed = comfyclient.model_files(manifest)
    for entry_values in planned:
        comfyclient.check_models(flow["graph"], entry_values, allowed)
    source = None if video else _source_path(flow, inputs)
    comfyclient.link_models(req, comfyclient.checkout(manifest, PULL_FIX), MODEL_DIRS)
    uploaded = comfyclient.upload(source) if source is not None else ""
    if source is not None:
        print(f"{source.name} uploaded as {uploaded}", flush=True)
    assets: list[dict[str, Any]] = []
    for entry, entry_values in zip(entries, planned, strict=True):
        if video:
            uploaded = _upload_entry(req, entry)
        if source is not None or video:
            entry_values["image"] = uploaded
        graph = comfyclient.fill(flow["graph"], entry_values)
        found = comfyclient.images(comfyclient.history(comfyclient.submit(graph)))
        for path in _save(found, str(entry["name"]), req.out_dir, draft):
            print(f"{path.name} ok", flush=True)
            assets.append(_asset({**entry_values, **meta}, path, video, draft))
    return {"tool": comfyclient.tool(manifest), "assets": assets}


def _entries(req: Request) -> dict[str, dict[str, Any]]:
    """The image entries by name: the piece's list, or one record's params.

    ``run`` and its verify get the piece's ``image`` array; ``facet check``
    and ``facet preview`` pass the record's params for one asset, which are
    the entry itself.
    """
    raw = dict(req.inputs).get("image")
    items = raw if isinstance(raw, list) else [req.inputs]
    return {str(item.get("name")): item for item in items if isinstance(item, dict)}


def _entry_for(entries: dict[str, dict[str, Any]], path: Path) -> dict[str, Any]:
    """The entry that produced ``path``: its own name, else the first entry."""
    for name, entry in entries.items():
        if path.stem == name or path.stem.startswith(f"{name}-"):
            return entry
    return next(iter(entries.values()), {})


def _size(path: Path) -> tuple[int, int]:
    with PIL.Image.open(path) as image:
        width, height = image.size
    return int(width), int(height)


def _verify_video(entries: dict[str, dict[str, Any]], path: Path) -> dict[str, Any]:
    """The MP4 opens, at the entry's size, 24 fps and the entry's frame count."""
    entry = _entry_for(entries, path)
    thresholds: dict[str, Any] = {
        "width": int(entry.get("width", DEFAULT_CLIP_WIDTH)),
        "height": int(entry.get("height", DEFAULT_CLIP_HEIGHT)),
        "fps": VIDEO_FPS,
        "frames": int(entry.get("length", DEFAULT_CLIP_LENGTH)),
    }
    return comfyclient.verify_video(path, thresholds, VIDEO_FPS_TOLERANCE)


def _verify_asset(
    entries: dict[str, dict[str, Any]], path: Path, video: bool = False
) -> dict[str, Any]:
    """A clip's MP4 is probed with FFmpeg; a still's PNG with Pillow."""
    if video:
        return _verify_video(entries, path)
    entry = _entry_for(entries, path)
    expected_width = int(entry.get("width", DEFAULT_WIDTH))
    expected_height = int(entry.get("height", DEFAULT_HEIGHT))
    thresholds = {"width": expected_width, "height": expected_height}
    try:
        width, height = _size(path)
    except OSError as exc:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"error": str(exc)},
            "thresholds": thresholds,
            "verifier": "pillow",
        }
    passed = width == expected_width and height == expected_height
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {"width": width, "height": height},
        "thresholds": thresholds,
        "verifier": "pillow",
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    entries = _entries(req)
    video = req.capability == CLIP_CAPABILITY
    return {"assets": [_verify_asset(entries, path, video) for path in req.assets]}


def _preview_data(entry: dict[str, Any], path: Path) -> dict[str, Any]:
    """The image schema's fields, with the size measured from the PNG."""
    width, height = _size(path)
    name = str(entry.get("name", path.stem))
    seed = int(entry.get("seed", 0))
    return {
        "preview": 1,
        "kind": "image",
        "summary": f"{name} · {width}×{height} · seed {seed}",
        "name": name,
        "prompt": str(entry.get("prompt", "")),
        "seed": seed,
        "width": width,
        "height": height,
    }


def _preview_video(entry: dict[str, Any], path: Path) -> dict[str, Any]:
    """The video schema's fields, with the probe's measurements of the MP4."""
    probe = comfyclient.probe_video(path)
    name = str(entry.get("name", path.stem))
    seed = int(entry.get("seed", 0))
    fps = int(round(float(probe["fps"])))
    summary = (
        f"{name} · {probe['width']}×{probe['height']} · "
        f"{probe['frames']} frames · {fps} fps · seed {seed}"
    )
    return {
        "preview": 1,
        "kind": "video",
        "summary": summary,
        "name": name,
        "prompt": str(entry.get("prompt", "")),
        "seed": seed,
        "width": probe["width"],
        "height": probe["height"],
        "length": probe["frames"],
        "fps": fps,
    }


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    entries = _entries(req)
    video = req.capability == CLIP_CAPABILITY
    results: list[dict[str, Any]] = []
    for path in req.assets:
        entry = _entry_for(entries, path)
        data = _preview_video(entry, path) if video else _preview_data(entry, path)
        preview_name = f"{path.name}.preview.json"
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        results.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": results}


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    manifest = comfyclient.manifest(PACKAGE_DIR)
    checks = [
        comfyclient.doctor_gpu(),
        comfyclient.doctor_gpu_free(),
        comfyclient.doctor_models(req, manifest, PULL_FIX),
        comfyclient.doctor_checkout(manifest, PULL_FIX),
    ]
    if req.depth == "full":
        checks.append(comfyclient.doctor_server())
    return {"checks": checks}


runner.main()
